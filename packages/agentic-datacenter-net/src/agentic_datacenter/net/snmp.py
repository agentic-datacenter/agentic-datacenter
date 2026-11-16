"""The SNMP view of the point database (SDD 8, ADR 0014).

One agent serves every SNMP-mapped point under the fictitious enterprise arc
of :mod:`agentic_datacenter.net.maps`. A read is answered with what the point database
holds at that moment. Nothing can be written: a SET is answered
``notWritable`` and recorded as a device violation.

Identifiers: the value of a point is at the identifier its map gives,
``<base>.<device>.<index>.0``; the quality of the same sample is at
``<base>.0.<device>.<index>.0``.

Encoding: an analog value is an ``Integer32`` holding the value times
:data:`SCALE`; a counter is a ``Counter64``; a binary point is 1 for true and
2 for false; an enumerated status is the position of the state in the point's
declared list, counted from 1; a quality is its code in :data:`QUALITY_CODE`.

Only SNMPv3 is answered, for one user with authentication and no privacy. The
user and its key are constants here and are not secrets: the simulator binds
inside its own networks and holds nothing to protect.

The agent answers at once: the response latency of section 8.4 is not modelled.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
import threading
from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from pysnmp.carrier.asyncio.dgram import udp, udp6  # type: ignore[import-untyped]
from pysnmp.entity import config, engine  # type: ignore[import-untyped]
from pysnmp.entity.rfc3413 import cmdrsp, context  # type: ignore[import-untyped]
from pysnmp.proto import rfc1902, rfc1905  # type: ignore[import-untyped]
from pysnmp.smi import error as smi_error  # type: ignore[import-untyped]
from pysnmp.smi import instrum

from agentic_datacenter.core.io import PointDecl, PointValue
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.net.guard import check_bind
from agentic_datacenter.net.maps import SNMP_BASE, PointMap, _mapped
from agentic_datacenter.supervisory.points import PointDatabase

#: An analog value goes on the wire as ``round(value * SCALE)``.
SCALE = 1000
#: The quality of a sample, as the integer served in the quality subtree.
QUALITY_CODE = {"good": 1, "uncertain": 2, "bad": 3, "stale": 4}
#: The one SNMPv3 user of the simulator and its HMAC-SHA-256 key. Not secrets.
USER = "agentic-datacenter-monitor"
AUTH_KEY = "agentic-datacenter-simulation-only"
_INT32 = (-(2**31), 2**31 - 1)
_BASE = tuple(int(arc) for arc in SNMP_BASE.split("."))
_QUALITY_ARC = 0

type _Oid = tuple[int, ...]


@dataclass(frozen=True)
class SnmpAnswer:
    """What the view says about one identifier.

    ``syntax`` is ``Integer32`` or ``Counter64`` with the integer in ``value``,
    or one of the exceptions ``noSuchObject``, ``noSuchInstance`` and
    ``endOfMibView`` with no value.
    """

    oid: str
    syntax: str
    value: int | None = None


def _key(oid: str) -> _Oid:
    try:
        return tuple(int(arc) for arc in oid.strip(".").split("."))
    except ValueError:
        raise ValueError(f"{oid!r} is not an object identifier") from None


def _text(key: _Oid) -> str:
    return ".".join(str(arc) for arc in key)


def quality_oid(oid: str) -> str:
    """Return where the quality of the value at *oid* is served."""
    key = _key(oid)
    if key[: len(_BASE)] != _BASE:
        raise ValueError(f"{oid} is not under {SNMP_BASE}")
    return _text((*_BASE, _QUALITY_ARC, *key[len(_BASE) :]))


def encode(value: PointValue, decl: PointDecl) -> tuple[str, int]:
    """Return the SNMP type and the integer that stand for *value* on the wire."""
    if decl.kind.startswith("binary"):
        return "Integer32", 1 if value else 2
    if decl.kind == "enum_status":
        return "Integer32", (decl.values or ()).index(str(value)) + 1
    if decl.kind == "counter":
        return "Counter64", int(value) & 0xFFFFFFFFFFFFFFFF
    return "Integer32", min(max(round(float(value) * SCALE), _INT32[0]), _INT32[1])


def decode(raw: int, decl: PointDecl) -> PointValue:
    """Return the value that the integer *raw* stands for.

    Raises:
        ValueError: If the integer is not a value of this point.
    """
    if decl.kind.startswith("binary"):
        if raw not in (1, 2):
            raise ValueError(f"{raw} is neither true (1) nor false (2)")
        return raw == 1
    if decl.kind == "enum_status":
        values = decl.values or ()
        if not 1 <= raw <= len(values):
            raise ValueError(f"{raw} is not one of the {len(values)} states")
        return values[raw - 1]
    if decl.kind == "counter":
        return raw
    return raw / SCALE


class SnmpView:
    """Every SNMP-mapped point of the facility, as a read-only tree of identifiers."""

    def __init__(self, kernel: Kernel, points: PointDatabase, maps: Sequence[PointMap]) -> None:
        """Build the tree from the SNMP *maps*; maps of other protocols are ignored.

        Raises:
            ValueError: If a map names a point that may have no protocol map
                (ADR 0010), or an identifier outside the simulator's arc.
        """
        self._kernel, self._points = kernel, points
        self.lock = threading.Lock()
        self._violations: list[dict[str, JsonValue]] = []
        #: identifier -> (map, whether it is the quality rather than the value)
        self._entries: dict[_Oid, tuple[PointMap, bool]] = {}
        for m in maps:
            if m.protocol != "snmp":
                continue
            record = points.read(m.tag)
            if not _mapped(record.zone, record.tier, record.kind):
                raise ValueError(f"{m.tag} has no protocol map (ADR 0010) and cannot be served")
            key = _key(str(m.address))
            device = key[len(_BASE) : len(_BASE) + 1]
            if key[: len(_BASE)] != _BASE or device == (_QUALITY_ARC,) or key[-1] != 0:
                raise ValueError(f"{m.address} is not a scalar under {SNMP_BASE}")
            self._entries[key] = (m, False)
            self._entries[_key(quality_oid(str(m.address)))] = (m, True)
        self._order = sorted(self._entries)
        self._objects = {key[:-1] for key in self._order}

    def oids(self) -> list[str]:
        """Return every identifier served, in the order a walk visits them."""
        return [_text(key) for key in self._order]

    def _answer(self, key: _Oid) -> SnmpAnswer:
        m, is_quality = self._entries[key]
        record = self._points.read(m.tag)
        if is_quality:
            return SnmpAnswer(_text(key), "Integer32", QUALITY_CODE[record.quality])
        syntax, value = encode(record.value, self._points.declaration(m.tag))
        return SnmpAnswer(_text(key), syntax, value)

    def get(self, oid: str) -> SnmpAnswer:
        """Return the value at *oid*, or the exception a GET of it gets."""
        key = _key(oid)
        if key in self._entries:
            return self._answer(key)
        # An object of the view named without its instance, or with another one.
        known = any(key[:length] in self._objects for length in range(len(_BASE) + 2, len(key) + 1))
        return SnmpAnswer(oid, "noSuchInstance" if known else "noSuchObject")

    def get_next(self, oid: str) -> SnmpAnswer:
        """Return the first value after *oid*, arc by arc as numbers, or ``endOfMibView``."""
        position = bisect_right(self._order, _key(oid))
        if position == len(self._order):
            return SnmpAnswer(oid, "endOfMibView")
        return self._answer(self._order[position])

    def set(self, oid: str, source: str = "") -> str:
        """Refuse a SET of *oid* from *source*, record it, and return the error status."""
        found = self._entries.get(_key(oid))
        m = found[0] if found else None
        entry: dict[str, JsonValue] = {
            "time_ms": self._kernel.clock.now_ms,
            "device": m.device if m else "",
            "unit": m.device_number if m else 0,
            "function": "set",
            "address": oid,
            "tag": m.tag if m else "",
            "reason": "the SNMP view is read-only" if m else "no point at this identifier",
            "source": source,
        }
        self._violations.append(entry)
        self._kernel.events.publish("net.device_violation", entry)
        return "notWritable"

    def violations(self) -> list[dict[str, JsonValue]]:
        """Return every refused SET so far."""
        return [dict(entry) for entry in self._violations]


_EXCEPTIONS = {
    "noSuchObject": rfc1905.noSuchObject,
    "noSuchInstance": rfc1905.noSuchInstance,
    "endOfMibView": rfc1905.endOfMibView,
}


def _wire(answer: SnmpAnswer) -> Any:
    if answer.value is None:
        return _EXCEPTIONS[answer.syntax]
    if answer.syntax == "Counter64":
        return rfc1902.Counter64(answer.value)
    return rfc1902.Integer32(answer.value)


class _Instrumentation(instrum.AbstractMibInstrumController):  # type: ignore[misc]
    """What the library asks instead of its own MIB tree: the view."""

    def __init__(self, view: SnmpView) -> None:
        self._view = view

    def read_variables(self, *var_binds: Any, **context: Any) -> list[tuple[Any, Any]]:
        """Answer a GET."""
        with self._view.lock:
            return [(name, _wire(self._view.get(_text(tuple(name))))) for name, _ in var_binds]

    def read_next_variables(self, *var_binds: Any, **context: Any) -> list[tuple[Any, Any]]:
        """Answer a GETNEXT, or one repetition of a GETBULK."""
        out = []
        with self._view.lock:
            for name, _ in var_binds:
                answer = self._view.get_next(_text(tuple(name)))
                out.append((rfc1902.ObjectName(answer.oid), _wire(answer)))
        return out

    def write_variables(self, *var_binds: Any, **context: Any) -> list[tuple[Any, Any]]:
        """Refuse a SET: every variable is recorded, the first one is reported."""
        request = context["snmpEngine"].observer.get_execution_context(
            "rfc3412.receiveMessage:request"
        )
        host, port = request["transportAddress"][:2]
        with self._view.lock:
            for name, _ in var_binds:
                self._view.set(_text(tuple(name)), source=f"{host}:{port}")
        raise smi_error.NotWritableError(name=var_binds[0][0], idx=0)


class SnmpAgent:
    """Serves an :class:`SnmpView` on a UDP port, from a thread of its own."""

    def __init__(self, view: SnmpView, user: str = USER, auth_key: str = AUTH_KEY) -> None:
        """Create the agent; nothing is bound until :meth:`start`."""
        self.view = view
        self._user, self._auth_key = user, auth_key
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self, host: str, port: int, allow_external: bool = False) -> int:
        """Bind *host*:*port* (0 picks a free port) and serve. Return the port.

        Raises:
            ExternalAddressError: If the address is outside the simulator's own
                networks and *allow_external* is not set (ADC-SAF-001).
            RuntimeError: If the agent is already serving or did not start.
        """
        check_bind(host, allow_external=allow_external)
        if self._thread is not None:
            raise RuntimeError("the SNMP agent is already serving")
        address = "127.0.0.1" if host == "localhost" else host
        v6 = ipaddress.ip_address(address).version == 6
        # Bound here, so a port that is taken is reported to the caller, and a
        # request that arrives before the loop runs waits in the socket.
        sock = socket.socket(socket.AF_INET6 if v6 else socket.AF_INET, socket.SOCK_DGRAM)
        try:
            sock.bind((address, port))
        except OSError:
            sock.close()
            raise
        sock.setblocking(False)
        bound = int(sock.getsockname()[1])
        ready = threading.Event()
        failed: list[BaseException] = []

        def run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            snmp_engine = None
            try:
                snmp_engine = self._engine(loop, sock, v6)
                self._loop = loop
                loop.call_soon(ready.set)
                loop.run_forever()
            except BaseException as exc:  # noqa: BLE001 - reported to the caller below
                failed.append(exc)
                ready.set()
            finally:
                if snmp_engine is not None:
                    snmp_engine.close_dispatcher()
                    # Let the transport finish closing its socket.
                    loop.run_until_complete(asyncio.sleep(0))
                else:
                    sock.close()
                loop.close()

        self._thread = threading.Thread(target=run, name="agentic-datacenter-snmp", daemon=True)
        self._thread.start()
        if not ready.wait(10.0) or failed:
            self._thread.join(10.0)
            self._thread = self._loop = None
            raise RuntimeError(
                f"the SNMP agent did not start: {failed[0] if failed else 'timeout'}"
            )
        return bound

    def _engine(self, loop: asyncio.AbstractEventLoop, sock: socket.socket, v6: bool) -> Any:
        """Build the library's engine: one transport, one user, the view as its only content."""
        snmp_engine = engine.SnmpEngine()
        domain, protocol = (
            (udp6.DOMAIN_NAME, udp6.Udp6Transport) if v6 else (udp.DOMAIN_NAME, udp.UdpTransport)
        )
        transport = protocol(loop=loop).open_server_mode(sock=sock)
        config.add_transport(snmp_engine, domain, transport)
        config.add_v3_user(snmp_engine, self._user, config.USM_AUTH_HMAC192_SHA256, self._auth_key)
        snmp_context = context.SnmpContext(snmp_engine)
        snmp_context.unregister_context_name(b"")
        snmp_context.register_context_name(b"", _Instrumentation(self.view))
        for responder in (
            cmdrsp.GetCommandResponder,
            cmdrsp.NextCommandResponder,
            cmdrsp.BulkCommandResponder,
            cmdrsp.SetCommandResponder,
        ):
            responder(snmp_engine, snmp_context)
        return snmp_engine

    def stop(self) -> None:
        """Stop serving and release the port."""
        if self._loop is None or self._thread is None:
            return
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join(10.0)
        self._thread = self._loop = None
