"""One MMS server per relay, on ``libiec61850`` (SDD 8.5, ADR 0017).

The data model is built from the generated SCD, attribute by attribute, so
what a client finds in the directory is what the engineering file says. The
values come from :class:`~agentic_datacenter_iec61850.view.RelayView` after every step.

What a client may do: associate, browse, read, and enable the configured
reports. Everything else is refused with an access error, and where the
library tells the server about the attempt it becomes a device violation
event with the client's address:

- operate on a control object (every one is status-only);
- a write to configuration, description or setting data, or to a data set;
- any write to the setting-group control block;
- every file service;
- a change to a report control block beyond enabling it.

Three limits of the library are worked around or left standing; ADR 0017 has
the detail. A status-only control object is refused inside the library
without a word to the server, so the control objects are registered there as
direct-operate with a check that refuses every request, while the served
``ctlModel`` stays status-only. A select has no object to address and gets
"object does not exist" with no event. The file handler is not told who is
asking, so its event names every client connected at that moment.
"""

from __future__ import annotations

import socket
from typing import Any

from agentic_datacenter_iec61850 import library
from agentic_datacenter_iec61850.guard import check_bind
from agentic_datacenter_iec61850.scl import Ied, Leaf
from agentic_datacenter_iec61850.view import RelayView, Sample

_TYPES = {
    "BOOLEAN": "IEC61850_BOOLEAN", "INT32": "IEC61850_INT32", "INT8U": "IEC61850_INT8U",
    "FLOAT32": "IEC61850_FLOAT32", "Enum": "IEC61850_ENUMERATED", "Dbpos": "IEC61850_CODEDENUM",
    "Quality": "IEC61850_QUALITY", "Timestamp": "IEC61850_TIMESTAMP",
    "VisString255": "IEC61850_VISIBLE_STRING_255", "Octet64": "IEC61850_OCTET_STRING_64",
    "Check": "IEC61850_CHECK",
}  # fmt: skip
_CONFIGURATION = ("CF", "DC", "SP", "SV", "SE")
#: What a client may write in a report control block: subscribing, not reconfiguring.
_SUBSCRIBE = ("RptEna", "GI", "Resv", "ResvTms", "EntryID", "PurgeBuf")
_FILE_SERVICES = ("directory", "open", "obtain", "delete", "rename")


class Iec61850Server:
    """Serves one relay of a :class:`RelayView` on a TCP port."""

    def __init__(self, view: RelayView, relay: str) -> None:
        """Create the server of *relay* (its tag); nothing is bound until :meth:`start`.

        Raises:
            KeyError: If the view has no such relay.
            LibraryUnavailableError: If the protocol library is not installed.
        """
        self.view, self.relay = view, relay
        self.ied: Ied = view.ieds[relay]
        self._lib, self._k = library.load(), library.constants()
        self._server: int | None = None
        self._model: int | None = None
        self._attributes: dict[str, int] = {}
        self._leaves: dict[str, Leaf] = {leaf.ref: leaf for leaf in self.ied.leaves}
        self._pushed: dict[str, Sample] = {}
        self._peers: dict[int, str] = {}
        self._written: list[str] = []
        self._callbacks: list[Any] = []

    # -- building the model from the engineering file -------------------------------------------

    def _build(self) -> tuple[int, dict[str, int]]:
        lib, k, ied = self._lib, self._k, self.ied
        model = lib.IedModel_create(ied.name.encode())
        device = lib.LogicalDevice_create(b"LD0", model)
        nodes: dict[str, int] = {}
        for name in ied.logical_nodes:
            nodes[f"LD0/{name}"] = lib.LogicalNode_create(name.encode(), device)
        triggers = {"dchg": k.TRG_OPT_DATA_CHANGED, "qchg": k.TRG_OPT_QUALITY_CHANGED, "": 0}
        for leaf in ied.leaves:
            node, _, path = leaf.ref.partition(".")
            parent, ref = nodes[node], node
            parts = path.split(".")
            fc = getattr(k, f"IEC61850_FC_{leaf.fc}")
            for position, part in enumerate(parts, start=1):
                ref = f"{ref}.{part}"
                # The same name can be a structure under two functional constraints.
                key = ref if position <= leaf.depth else f"{ref}[{leaf.fc}]"
                if key not in nodes:
                    if position <= leaf.depth:
                        nodes[key] = lib.DataObject_create(part.encode(), parent, 0)
                    else:
                        last = position == len(parts)
                        kind = getattr(k, _TYPES[leaf.btype]) if last else k.IEC61850_CONSTRUCTED
                        nodes[key] = lib.DataAttribute_create(
                            part.encode(), parent, kind, fc, triggers[leaf.trigger], 0, 0
                        )
                parent = nodes[key]
        lln0 = nodes["LD0/LLN0"]
        for data_set in ied.data_sets:
            created = lib.DataSet_create(data_set.name.encode(), lln0)
            for member in data_set.members:
                node, _, rest = member.removeprefix("LD0/").partition(".")
                data, _, fc = rest.rstrip("]").partition("[")
                variable = f"{node}${fc}${data.replace('.', '$')}"
                lib.DataSetEntry_create(created, variable.encode(), -1, None)
        trigger = k.TRG_OPT_DATA_CHANGED | k.TRG_OPT_QUALITY_CHANGED | k.TRG_OPT_GI
        options = (
            k.RPT_OPT_SEQ_NUM | k.RPT_OPT_TIME_STAMP | k.RPT_OPT_REASON_FOR_INCLUSION
            | k.RPT_OPT_DATA_SET | k.RPT_OPT_ENTRY_ID
        )  # fmt: skip
        for report in ied.reports:
            lib.ReportControlBlock_create(
                report.name.encode(), lln0, report.report_id.encode(), report.buffered,
                report.data_set.encode(), 1, trigger, options, 0, 0,
            )  # fmt: skip
        lib.SettingGroupControlBlock_create(lln0, *ied.setting_groups)
        return model, nodes

    def _attribute(self, nodes: dict[str, int], leaf: Leaf) -> int:
        return nodes[f"{leaf.ref}[{leaf.fc}]"]

    def _set(self, leaf: Leaf, value: bool | int | float | str) -> None:
        lib, k, server = self._lib, self._k, self._server
        attribute = self._attributes[leaf.ref]
        if leaf.btype == "BOOLEAN":
            lib.IedServer_updateBooleanAttributeValue(server, attribute, bool(value))
        elif leaf.btype == "FLOAT32":
            lib.IedServer_updateFloatAttributeValue(server, attribute, float(value))
        elif leaf.btype == "Dbpos":
            lib.IedServer_updateDbposValue(server, attribute, k.DBPOS_ON if value else k.DBPOS_OFF)
        elif leaf.btype in ("INT32", "INT8U", "Enum"):
            lib.IedServer_updateInt32AttributeValue(server, attribute, int(value))
        elif leaf.btype == "VisString255":
            lib.IedServer_updateVisibleStringAttributeValue(server, attribute, str(value).encode())
        elif leaf.btype == "Timestamp":
            lib.IedServer_updateUTCTimeAttributeValue(server, attribute, int(value))
        elif leaf.btype == "Quality":
            lib.IedServer_updateQuality(server, attribute, self._quality(str(value)))

    def _quality(self, quality: str) -> int:
        k = library.CONSTANTS
        return {
            "good": k["QUALITY_VALIDITY_GOOD"],
            "uncertain": k["QUALITY_VALIDITY_QUESTIONABLE"],
            "bad": k["QUALITY_VALIDITY_INVALID"],
            "stale": k["QUALITY_VALIDITY_QUESTIONABLE"] | k["QUALITY_DETAIL_OLD_DATA"],
        }[quality]

    def _configure(self) -> None:
        """Put the configured values and the start time into the fresh model."""
        start = self.view.start_ms()
        for leaf in self.ied.leaves:
            if leaf.btype == "Timestamp" and leaf.fc != "CO":
                self._set(leaf, start)
            elif leaf.ordinal is not None:
                self._set(leaf, leaf.ordinal)
            elif leaf.value:
                self._set(leaf, leaf.value == "true" if leaf.btype == "BOOLEAN" else leaf.value)

    # -- refusing ---------------------------------------------------------------------------------

    def _client(self, connection: int | None) -> str:
        if not connection:
            return ""
        address = self._lib.ClientConnection_getPeerAddress(connection)
        return address.decode() if address else ""

    def _refuse(self, service: str, reference: str, client: str, reason: str) -> None:
        self.view.refuse(self.relay, service, reference, client, reason)

    def _install(self, nodes: dict[str, int]) -> None:
        lib, k, server = self._lib, self._k, self._server
        denied = k.DATA_ACCESS_ERROR_OBJECT_ACCESS_DENIED

        def on_connection(_server: int, connection: int, connected: bool, _: int) -> None:
            if connected:
                self._peers[connection] = self._client(connection)
            else:
                self._peers.pop(connection, None)

        def on_write(_attribute: int, _value: int, connection: int, index: int) -> int:
            reference = self._written[(index or 1) - 1]
            self._refuse("configuration-write", reference, self._client(connection),
                         "the relay takes no configuration over the network")  # fmt: skip
            return int(denied)

        def on_check(action: int, index: int, _value: int, _test: bool, _lock: bool) -> int:
            connection = lib.ControlAction_getClientConnection(action)
            self._refuse("control", self._written[(index or 1) - 1], self._client(connection),
                         "every control object is status-only")  # fmt: skip
            return int(k.CONTROL_OBJECT_ACCESS_DENIED)

        def on_block(
            _: int, connection: int, acsi_class: int, _device: int, node: int, name: bytes,
            member: bytes, access: int,
        ) -> bool:  # fmt: skip
            del node
            if access != k.IEC61850_CB_ACCESS_TYPE_WRITE:
                return True
            what = f"{(name or b'').decode()}.{(member or b'').decode()}"
            if acsi_class == k.ACSI_CLASS_SGCB:
                self._refuse("setting-group", f"LD0/LLN0.{what}", self._client(connection),
                             "setting groups are changed at the relay only")  # fmt: skip
                return False
            if (member or b"").decode() in _SUBSCRIBE:
                return True
            self._refuse("configuration-write", f"LD0/LLN0.{what}", self._client(connection),
                         "a report control block is not reconfigured over the network")  # fmt: skip
            return False

        def on_data_set(_: int, connection: int, operation: int, reference: bytes) -> bool:
            if operation in (k.DATASET_READ, k.DATASET_GET_DIRECTORY):
                return True
            self._refuse("configuration-write", (reference or b"").decode(),
                         self._client(connection), "data sets are fixed")  # fmt: skip
            return False

        def on_file(_: int, _connection: int, service: int, name: bytes, other: bytes) -> int:
            del other
            detail = f"{_FILE_SERVICES[service]} {(name or b'').decode()}".strip()
            self._refuse("file", detail, ", ".join(sorted(self._peers.values())),
                         "the relay offers no file service")  # fmt: skip
            return int(k.MMS_ERROR_FILE_FILE_ACCESS_DENIED)

        handlers = (
            library.ConnectionHandler(on_connection), library.WriteAccessHandler(on_write),
            library.PerformCheckHandler(on_check), library.ControlBlockAccessHandler(on_block),
            library.DataSetAccessHandler(on_data_set), library.FileAccessHandler(on_file),
        )  # fmt: skip
        self._callbacks = list(handlers)
        connection, write, check, block, data_set, file = handlers
        lib.IedServer_setConnectionIndicationHandler(server, connection, None)
        lib.IedServer_setControlBlockAccessHandler(server, block, None)
        lib.IedServer_setDataSetAccessHandler(server, data_set, None)
        lib.MmsServer_installFileAccessHandler(lib.IedServer_getMmsServer(server), file, None)
        for fc in _CONFIGURATION:
            lib.IedServer_setWriteAccessPolicy(
                server, getattr(k, f"IEC61850_FC_{fc}"), k.ACCESS_POLICY_DENY
            )
        for key, pointer in nodes.items():
            reference, _, fc = key.rstrip("]").partition("[")
            if fc in _CONFIGURATION:
                self._written.append(reference)
                lib.IedServer_handleWriteAccess(server, pointer, write, len(self._written))
        for leaf in self.ied.leaves:
            if leaf.fc == "CO" and leaf.ref.endswith(".Oper.ctlVal"):
                data = leaf.ref.removesuffix(".Oper.ctlVal")
                self._written.append(data)
                # See the module docstring: the library keeps its own copy of the
                # control model, and only a model other than status-only is checked.
                lib.IedServer_updateCtlModel(server, nodes[data], k.CONTROL_MODEL_DIRECT_NORMAL)
                lib.IedServer_setPerformCheckHandler(server, nodes[data], check, len(self._written))

    # -- serving ----------------------------------------------------------------------------------

    def _push(self) -> None:
        """Serve the view's present samples; called after every step."""
        server = self._server
        if server is None:
            return
        samples = self.view.samples(self.relay)
        changed = {ref: s for ref, s in samples.items() if self._pushed.get(ref) != s}
        if not changed:
            return
        lib = self._lib
        lib.IedServer_lockDataModel(server)
        try:
            # Time and quality first, so a report triggered by the value carries them.
            for ref, sample in changed.items():
                data = self.view.data_object(self.relay, ref)
                for name, value in (("t", sample.time_ms), ("q", sample.quality)):
                    leaf = self._leaves.get(f"{data}.{name}")
                    if leaf is not None:
                        self._set(leaf, value)
            for ref, sample in changed.items():
                self._set(self._leaves[ref], sample.value)
        finally:
            lib.IedServer_unlockDataModel(server)
        self._pushed.update(changed)

    def start(self, host: str, port: int, allow_external: bool = False) -> int:
        """Bind *host*:*port* (0 picks a free port) and serve. Return the port.

        Raises:
            ExternalAddressError: If the address is not loopback and
                *allow_external* is not set (ADC-SAF-001).
            RuntimeError: If the server is already running or cannot listen.
        """
        check_bind(host, allow_external=allow_external)
        if self._server is not None:
            raise RuntimeError(f"{self.relay} is already being served")
        if port == 0:
            with socket.socket() as probe:
                probe.bind((host, 0))
                port = int(probe.getsockname()[1])
        lib = self._lib
        self._model, nodes = self._build()
        self._server = lib.IedServer_create(self._model)
        self._attributes = {leaf.ref: self._attribute(nodes, leaf) for leaf in self.ied.leaves}
        self._install(nodes)
        self._configure()
        self._pushed = {}
        self._push()
        address = "127.0.0.1" if host == "localhost" else host
        lib.IedServer_setLocalIpAddress(self._server, address.encode())
        lib.IedServer_start(self._server, port)
        if not lib.IedServer_isRunning(self._server):
            self._destroy()
            raise RuntimeError(f"the MMS server of {self.relay} could not listen on {host}:{port}")
        self.view.follow(self._push)
        return port

    def _destroy(self) -> None:
        self._lib.IedServer_destroy(self._server)
        self._lib.IedModel_destroy(self._model)
        self._server = self._model = None
        self._callbacks, self._written, self._peers = [], [], {}

    def stop(self) -> None:
        """Stop serving and release the port."""
        if self._server is None:
            return
        self.view.unfollow(self._push)
        self._lib.IedServer_stop(self._server)
        self._destroy()
