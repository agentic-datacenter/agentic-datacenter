"""The OPC UA view of the point database (SDD 8.3, ADR 0015).

One server, the host ``opcua-server`` in ``Z2-SUP``, northbound over conduit
``C2``. Every point with an OPC UA map is the variable ``ns=2;s=<tag>`` under
one object per device. A read is answered with what the point database holds
at that moment: the value, a status code made from the point quality, and two
timestamps in simulated time. Nothing is writable; a write is answered
``BadUserAccessDenied`` and recorded as a device violation.

Simulated time has no calendar date, so a timestamp is simulated milliseconds
after :data:`SIM_EPOCH`. The wall clock is never read here.

Given a certificate the server offers sign and encrypt only and refuses a
session on an unsecured channel. Without one it is unsecured and binds to
loopback only. The server answers at once: the response latency of section
8.4 is not modelled, and subscriptions do not follow the plant (clients poll).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import threading
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from asyncua import ua
from asyncua.common.callback import CallbackType
from asyncua.crypto.permission_rules import User, UserRole
from asyncua.server.server import Server
from asyncua.server.user_managers import UserManager
from asyncua.ua.attribute_ids import AttributeIds
from asyncua.ua.status_codes import StatusCodes

from agentic_datacenter.core.io import PointValue
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.net.guard import check_bind
from agentic_datacenter.net.maps import PointMap
from agentic_datacenter.supervisory.points import PointDatabase

#: The namespace of the points; it is namespace index 2 on the server.
NAMESPACE_URI = "urn:agentic-datacenter:points"
NAMESPACE_INDEX = 2
#: The instant that simulated time zero is written as on the wire.
SIM_EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
#: The status code a point of each quality is read with.
STATUS_OF_QUALITY: dict[str, int] = {
    "good": int(StatusCodes.Good),
    "uncertain": int(StatusCodes.Uncertain),
    "stale": int(StatusCodes.UncertainLastUsableValue),
    "bad": int(StatusCodes.Bad),
}
_PREFIX = f"ns={NAMESPACE_INDEX};s="


class InsecureEndpointError(RuntimeError):
    """An unsecured OPC UA endpoint was about to be bound outside loopback."""


def _variant_type(kind: str) -> ua.VariantType:
    if kind.startswith("binary"):
        return ua.VariantType.Boolean
    if kind == "counter":
        return ua.VariantType.UInt64
    if kind == "enum_status":
        return ua.VariantType.String
    return ua.VariantType.Double


class OpcUaView:
    """The OPC UA nodes of the facility, as views of the point database. Opens no socket."""

    def __init__(self, kernel: Kernel, points: PointDatabase, maps: Sequence[PointMap]) -> None:
        """Index the OPC UA *maps*; maps of other protocols are ignored.

        Raises:
            ValueError: If a map's node id is not ``ns=2;s=<tag>``.
        """
        self._kernel, self._points = kernel, points
        self.lock = threading.Lock()
        self._violations: list[dict[str, JsonValue]] = []
        self._tags: dict[str, str] = {}
        self._types: dict[str, ua.VariantType] = {}
        self._host = "opcua-server"
        for m in maps:
            if m.protocol != "opcua":
                continue
            if m.address != _PREFIX + m.tag or m.writable:
                raise ValueError(f"{m.tag}: not a read-only node {_PREFIX}<tag>: {m.address}")
            self._tags[str(m.address)] = m.tag
            self._types[m.tag] = _variant_type(points.declaration(m.tag).kind)
            self._host = m.device

    def node_ids(self) -> list[str]:
        """Return the node id of every served point, sorted."""
        return sorted(self._tags)

    def tag_of(self, node_id: str) -> str:
        """Return the tag served at *node_id*.

        Raises:
            KeyError: If no point is served there.
        """
        return self._tags[node_id]

    def node_of(self, tag: str) -> str:
        """Return the node id point *tag* is served at.

        Raises:
            KeyError: If the point is not served.
        """
        if tag not in self._types:
            raise KeyError(f"no OPC UA node for {tag}")
        return _PREFIX + tag

    def devices(self) -> list[str]:
        """Return every device that has a served point, sorted. Each is one object node."""
        return sorted({tag.rpartition(".")[0] for tag in self._types})

    def variant_type(self, tag: str) -> ua.VariantType:
        """Return the type the value of point *tag* is sent as."""
        return self._types[tag]

    def description(self, tag: str) -> str:
        """Return the description of point *tag*."""
        return self._points.declaration(tag).description

    def timestamp(self, time_ms: int) -> ua.DateTime:
        """Return simulated time *time_ms* as it is written on the wire."""
        # The library's DateTime is a plain datetime under another name.
        return cast(ua.DateTime, SIM_EPOCH + timedelta(milliseconds=time_ms))

    def data_value(self, tag: str) -> ua.DataValue:
        """Return what a read of point *tag* answers now: value, status and timestamps."""
        with self.lock:
            record = self._points.read(tag)
            now_ms = self._kernel.clock.now_ms
        kind = self._types[tag]
        value: PointValue = record.value
        if kind == ua.VariantType.Double:
            value = float(value)
        return ua.DataValue(
            ua.Variant(value, kind),
            ua.StatusCode(ua.UInt32(STATUS_OF_QUALITY[record.quality])),
            SourceTimestamp=self.timestamp(record.time_ms),
            ServerTimestamp=self.timestamp(now_ms),
        )

    def refuse_write(self, node_id: str, attribute: int) -> None:
        """Record a write that was refused, as a device violation (SDD 8.4)."""
        with self.lock:
            entry: dict[str, JsonValue] = {
                "time_ms": self._kernel.clock.now_ms, "device": self._host, "node": node_id,
                "attribute": attribute, "tag": self._tags.get(node_id, ""),
                "reason": "the OPC UA view is read-only",
            }  # fmt: skip
            self._violations.append(entry)
            self._kernel.events.publish("net.device_violation", entry)

    def violations(self) -> list[dict[str, JsonValue]]:
        """Return every refused write so far."""
        return [dict(entry) for entry in self._violations]


class _Users(UserManager):
    """Everyone is an ordinary user; on a secured server only over a channel with a certificate."""

    def __init__(self, secured: bool) -> None:
        self._secured = secured

    def get_user(
        self,
        iserver: Any,
        username: str | None = None,
        password: str | None = None,
        certificate: Any = None,
    ) -> User | None:
        del iserver, username, password
        # An unsecured channel has no client certificate: the library passes none, or empty.
        if self._secured and not certificate:
            return None
        return User(role=UserRole.User)


def _is_loopback(host: str) -> bool:
    return host == "localhost" or ipaddress.ip_address(host).is_loopback


class OpcUaServer:
    """Serves an :class:`OpcUaView` on a TCP port, from a thread of its own."""

    def __init__(
        self,
        view: OpcUaView,
        certificate: Path | None = None,
        private_key: Path | None = None,
        application_uri: str = "urn:agentic-datacenter:opcua-server",
    ) -> None:
        """Create the server; nothing is bound until :meth:`start`.

        Args:
            view: What is served.
            certificate: The application certificate. With it the server offers
                sign and encrypt only; without it the server is unsecured.
            private_key: The key of *certificate*.
            application_uri: The application URI, which *certificate* must carry.

        Raises:
            ValueError: If only one of *certificate* and *private_key* is given.
        """
        if (certificate is None) != (private_key is None):
            raise ValueError("give both a certificate and its private key, or neither")
        self.view = view
        self._certificate, self._private_key = certificate, private_key
        self._application_uri = application_uri
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stopping: asyncio.Event | None = None

    @property
    def secured(self) -> bool:
        """Whether the server offers sign and encrypt only."""
        return self._certificate is not None

    async def _build(self, host: str, port: int) -> Server:
        server = Server(user_manager=_Users(self.secured))
        await server.init()
        literal = f"[{host}]" if ":" in host else host
        server.set_endpoint(f"opc.tcp://{literal}:{port}/")
        server.set_server_name("Agentic-Datacenter OPC UA server")
        await server.set_application_uri(self._application_uri)
        # The library would write the wall clock to its own Server object once a second.
        server.disable_clock(True)
        server.allow_remote_admin(False)
        server.set_identity_tokens([ua.AnonymousIdentityToken])
        if self._certificate is not None and self._private_key is not None:
            await server.load_certificate(self._certificate)
            await server.load_private_key(self._private_key)
            server.set_security_policy([ua.SecurityPolicyType.Basic256Sha256_SignAndEncrypt])
        else:
            server.set_security_policy([ua.SecurityPolicyType.NoSecurity])
        index = await server.register_namespace(NAMESPACE_URI)
        if index != NAMESPACE_INDEX:
            raise RuntimeError(f"namespace {NAMESPACE_URI} got index {index}")
        view = self.view

        def answer(node: ua.NodeId, attribute: AttributeIds) -> ua.DataValue:
            del attribute
            return view.data_value(str(node.Identifier))

        objects = {}
        for device in view.devices():
            objects[device] = await server.nodes.objects.add_object(
                ua.NodeId.from_string(_PREFIX + device), ua.QualifiedName(device, index)
            )
        for node_id in view.node_ids():
            tag = view.tag_of(node_id)
            device, _, name = tag.rpartition(".")
            kind = view.variant_type(tag)
            # The stored value is never read: the callback below answers every read.
            variable = await objects[device].add_variable(
                ua.NodeId.from_string(node_id), ua.QualifiedName(name, index),
                view.data_value(tag).Value, kind,
            )  # fmt: skip
            await variable.write_attribute(
                AttributeIds.Description,
                ua.DataValue(ua.Variant(ua.LocalizedText(view.description(tag)))),
            )
            server.set_attribute_value_callback(variable.nodeid, answer)

        def refused(event: Any, dispatcher: Any) -> None:
            del dispatcher
            if not event.is_external:
                return  # the library filling in its own Server object
            for write in event.request_params.NodesToWrite:
                view.refuse_write(write.NodeId.to_string(), int(write.AttributeId))

        server.subscribe_server_callback(CallbackType.PreWrite, refused)
        return server

    def start(self, host: str, port: int, allow_external: bool = False) -> int:
        """Bind *host*:*port* (0 picks a free port) and serve. Return the port.

        Raises:
            ExternalAddressError: If the address is outside the simulator's own
                networks and *allow_external* is not set (ADC-SAF-001).
            InsecureEndpointError: If the server has no certificate and the
                address is not loopback.
            RuntimeError: If the server is already running or does not start.
        """
        check_bind(host, allow_external=allow_external)
        if not self.secured and not _is_loopback(host):
            raise InsecureEndpointError(
                f"refusing to bind {host}: without a certificate the OPC UA server "
                "is unsecured and serves loopback only"
            )
        if self._thread is not None:
            raise RuntimeError("the OPC UA server is already running")
        if port == 0:
            with socket.socket() as probe:
                probe.bind((host, 0))
                port = int(probe.getsockname()[1])
        failed: list[BaseException] = []
        ready = threading.Event()

        def run() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop

            async def serve() -> None:
                self._stopping = asyncio.Event()
                server = await self._build(host, port)
                await server.start()
                ready.set()
                try:
                    await self._stopping.wait()
                finally:
                    await server.stop()

            try:
                loop.run_until_complete(serve())
            except BaseException as exc:  # noqa: BLE001 - reported to the caller below
                failed.append(exc)
            finally:
                ready.set()
                loop.close()

        self._thread = threading.Thread(target=run, name="agentic-datacenter-opcua", daemon=True)
        self._thread.start()
        started = ready.wait(60.0)
        if failed or not started:
            self._thread.join(1.0)
            self._thread = self._loop = self._stopping = None
            why = failed[0] if failed else "it did not start listening"
            raise RuntimeError(f"the OPC UA server did not start: {why}")
        return port

    def stop(self) -> None:
        """Stop serving and release the port."""
        if self._loop is None or self._stopping is None or self._thread is None:
            return
        self._loop.call_soon_threadsafe(self._stopping.set)
        self._thread.join(10.0)
        self._thread = self._loop = self._stopping = None
