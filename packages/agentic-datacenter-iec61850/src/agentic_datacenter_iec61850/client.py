"""An MMS client on ``libiec61850``, for the protocol tests and for looking at a relay.

It does what a supervisory client does (browse, read, take reports) and what
a misused one would try (operate, select, write, change the setting group,
use the file services), so the tests can show each answer on a real socket.
It connects to loopback only.
"""

from __future__ import annotations

import ctypes
import queue
from dataclasses import dataclass
from typing import Any

from agentic_datacenter_iec61850 import library
from agentic_datacenter_iec61850.guard import check_connect

#: A double-point position as the client decodes its two bits.
DBPOS = {0: "intermediate", 1: "on", 2: "off", 3: "bad"}
_VALIDITY = {0: "good", 1: "reserved", 2: "invalid", 3: "questionable"}
OLD_DATA = 128


def validity(quality: int) -> str:
    """Return the validity a quality value carries: good, invalid or questionable."""
    return _VALIDITY[quality & 3]


def old_data(quality: int) -> bool:
    """Return whether a quality value is flagged as old data."""
    return bool(quality & OLD_DATA)


@dataclass(frozen=True)
class Directory:
    """What one relay serves, as found by walking it.

    Attributes:
        domain: Name of the logical device on the wire.
        logical_nodes: Its logical nodes.
        attributes: ``(reference, functional constraint)`` of every basic
            attribute, with the reference as ``LD0/LN.DO.attribute``.
        control_blocks: ``(functional constraint, name)`` of each report and
            setting-group control block in ``LLN0``.
        data_sets: Data set name to its members.
    """

    domain: str
    logical_nodes: tuple[str, ...]
    attributes: frozenset[tuple[str, str]]
    control_blocks: frozenset[tuple[str, str]]
    data_sets: dict[str, tuple[str, ...]]


@dataclass(frozen=True)
class Report:
    """One received report: its control block and the members it includes."""

    control_block: str
    entries: tuple[tuple[str, str, Any], ...]

    def value(self, member: str) -> Any:
        """Return the value of data set member *member*, or None if it is not included."""
        return next((value for name, _, value in self.entries if name == member), None)


class MmsClient:
    """One association with one relay."""

    def __init__(self, host: str, port: int, timeout_ms: int = 5000) -> None:
        """Connect to *host*:*port*.

        Raises:
            ExternalAddressError: If *host* is not loopback (ADC-SAF-002).
            ConnectionError: If the relay does not answer.
        """
        check_connect(host)
        self._lib, self._k = library.load(), library.constants()
        self._error = ctypes.c_int(0)
        self._names = {
            number: name.removeprefix("IED_ERROR_").lower().replace("_", "-")
            for name, number in library.CONSTANTS.items()
            if name.startswith("IED_ERROR_")
        }
        self._reasons = {
            number: name.removeprefix("IEC61850_REASON_").lower().replace("_", "-")
            for name, number in library.CONSTANTS.items()
            if name.startswith("IEC61850_REASON_")
        }
        self.reports: queue.Queue[Report] = queue.Queue()
        self._handlers: list[Any] = []
        self._members: dict[str, tuple[str, ...]] = {}
        self._connection = self._lib.IedConnection_create()
        self._lib.IedConnection_setRequestTimeout(self._connection, timeout_ms)
        address = "127.0.0.1" if host == "localhost" else host
        self._lib.IedConnection_connect(self._connection, self._error, address.encode(), port)
        if self._error.value != self._k.IED_ERROR_OK:
            self._lib.IedConnection_destroy(self._connection)
            self._connection = None
            raise ConnectionError(f"no MMS association with {host}:{port}: {self._result()}")

    def __enter__(self) -> MmsClient:
        """Return the client; the association is closed on exit."""
        return self

    def __exit__(self, *_: object) -> None:
        """Close the association."""
        self.close()

    def close(self) -> None:
        """Release the association."""
        if self._connection is not None:
            self._lib.IedConnection_close(self._connection)
            self._lib.IedConnection_destroy(self._connection)
            self._connection = None

    def _result(self) -> str:
        return self._names.get(self._error.value, str(self._error.value))

    # -- discovery ------------------------------------------------------------------------------

    def logical_devices(self) -> list[str]:
        """Return the names of the logical devices the relay serves."""
        found = self._lib.IedConnection_getLogicalDeviceList(self._connection, self._error)
        return library.strings(found)

    def directory(self) -> Directory:
        """Walk the relay's first logical device and return everything it names."""
        lib, domain = self._lib, self.logical_devices()[0]
        names = library.strings(
            lib.IedConnection_getLogicalDeviceVariables(
                self._connection, self._error, domain.encode()
            )
        )
        nodes = tuple(n for n in names if "$" not in n)
        known = set(names)
        attributes, blocks = set(), set()
        for name in names:
            parts = name.split("$")
            if len(parts) >= 3 and (parts[1] in ("BR", "RP") or parts[2] == "SGCB"):
                blocks.add((parts[1], parts[2]))
            elif len(parts) >= 4 and not any(k.startswith(name + "$") for k in known):
                attributes.add((f"LD0/{parts[0]}.{'.'.join(parts[2:])}", parts[1]))
        sets = {}
        listed = lib.IedConnection_getLogicalDeviceDataSets(
            self._connection, self._error, domain.encode()
        )
        for entry in library.strings(listed):
            node, _, name = entry.partition("$")
            sets[name] = self._data_set(f"{domain}/{node}.{name}", domain)
        return Directory(domain, nodes, frozenset(attributes), frozenset(blocks), sets)

    def _data_set(self, reference: str, domain: str) -> tuple[str, ...]:
        deletable = ctypes.c_bool()
        members = library.strings(
            self._lib.IedConnection_getDataSetDirectory(
                self._connection, self._error, reference.encode(), deletable
            )
        )
        return tuple("LD0/" + m.removeprefix(domain + "/") for m in members)

    def kind(self, reference: str, fc: str) -> str:
        """Return the MMS type of an attribute: boolean, integer, float, bit-string ..."""
        lib, k = self._lib, self._k
        spec = lib.IedConnection_getVariableSpecification(
            self._connection, self._error, reference.encode(), getattr(k, f"IEC61850_FC_{fc}")
        )
        if not spec:
            return self._result()
        found = lib.MmsVariableSpecification_getType(spec)
        lib.MmsVariableSpecification_destroy(spec)
        return {
            k.MMS_BOOLEAN: "boolean", k.MMS_INTEGER: "integer", k.MMS_UNSIGNED: "unsigned",
            k.MMS_FLOAT: "float", k.MMS_BIT_STRING: "bit-string", k.MMS_UTC_TIME: "utc-time",
            k.MMS_VISIBLE_STRING: "visible-string", k.MMS_OCTET_STRING: "octet-string",
            k.MMS_STRUCTURE: "structure",
        }.get(found, str(found))  # fmt: skip

    # -- reading --------------------------------------------------------------------------------

    def _python(self, value: int) -> Any:
        lib, k = self._lib, self._k
        kind = lib.MmsValue_getType(value)
        if kind in (k.MMS_STRUCTURE, k.MMS_ARRAY):
            size = lib.MmsValue_getArraySize(value)
            return [self._python(lib.MmsValue_getElement(value, i)) for i in range(size)]
        if kind == k.MMS_BOOLEAN:
            return bool(lib.MmsValue_getBoolean(value))
        if kind == k.MMS_FLOAT:
            return float(lib.MmsValue_toFloat(value))
        if kind == k.MMS_INTEGER:
            return int(lib.MmsValue_toInt32(value))
        if kind == k.MMS_UNSIGNED:
            return int(lib.MmsValue_toUint32(value))
        if kind == k.MMS_BIT_STRING:
            return int(lib.MmsValue_getBitStringAsInteger(value))
        if kind == k.MMS_UTC_TIME:
            return int(lib.MmsValue_getUtcTimeInMs(value))
        if kind in (k.MMS_VISIBLE_STRING, k.MMS_STRING):
            return (lib.MmsValue_toString(value) or b"").decode()
        if kind == k.MMS_DATA_ACCESS_ERROR:
            return AccessError(int(lib.MmsValue_getDataAccessError(value)))
        return None

    def read(self, reference: str, fc: str) -> Any:
        """Read an attribute or a whole data object under one functional constraint.

        A structure comes back as a list, a bit string (quality, position) as
        an integer, a timestamp as milliseconds.

        Raises:
            AccessError: If the relay refuses or has no such object.
        """
        lib = self._lib
        value = lib.IedConnection_readObject(
            self._connection, self._error, reference.encode(),
            getattr(self._k, f"IEC61850_FC_{fc}"),
        )  # fmt: skip
        if not value:
            raise AccessError(self._error.value, self._result())
        try:
            out = self._python(value)
        finally:
            lib.MmsValue_delete(value)
        if isinstance(out, AccessError):
            raise out
        return out

    # -- reports --------------------------------------------------------------------------------

    def subscribe(self, control_block: str, general_interrogation: bool = False) -> str:
        """Enable report control block *control_block* (``<domain>/LLN0.BR.<name>``).

        Reports arrive in :attr:`reports`. Returns ``ok`` or the refusal.
        """
        lib, k = self._lib, self._k
        block = lib.IedConnection_getRCBValues(
            self._connection, self._error, control_block.encode(), None
        )
        if not block:
            return self._result()
        domain = control_block.partition("/")[0]
        data_set = (lib.ClientReportControlBlock_getDataSetReference(block) or b"").decode()
        self._members[control_block] = self._data_set(data_set.replace("$", "."), domain)

        def on_report(_: int, report: int) -> None:
            reference = lib.ClientReport_getRcbReference(report).decode()
            values = lib.ClientReport_getDataSetValues(report)
            entries = []
            for index, member in enumerate(self._members.get(reference, ())):
                reason = lib.ClientReport_getReasonForInclusion(report, index)
                if reason != k.IEC61850_REASON_NOT_INCLUDED:
                    value = self._python(lib.MmsValue_getElement(values, index))
                    entries.append((member, self._reasons.get(reason, str(reason)), value))
            self.reports.put(Report(reference, tuple(entries)))

        handler = library.ReportHandler(on_report)
        self._handlers.append(handler)
        lib.IedConnection_installReportHandler(
            self._connection, control_block.encode(),
            lib.ClientReportControlBlock_getRptId(block), handler, None,
        )  # fmt: skip
        lib.ClientReportControlBlock_setRptEna(block, True)
        mask = k.RCB_ELEMENT_RPT_ENA
        if general_interrogation:
            lib.ClientReportControlBlock_setGI(block, True)
            mask |= k.RCB_ELEMENT_GI
        lib.IedConnection_setRCBValues(self._connection, self._error, block, mask, True)
        result = self._result()
        lib.ClientReportControlBlock_destroy(block)
        return result

    def next_report(self, timeout_s: float = 5.0) -> Report | None:
        """Return the next report, or None if none arrives within *timeout_s* of real time."""
        try:
            return self.reports.get(timeout=timeout_s)
        except queue.Empty:
            return None

    # -- what a relay refuses -------------------------------------------------------------------

    def _write(self, reference: str, fc: str, value: int) -> str:
        lib = self._lib
        lib.IedConnection_writeObject(
            self._connection, self._error, reference.encode(),
            getattr(self._k, f"IEC61850_FC_{fc}"), value,
        )  # fmt: skip
        lib.MmsValue_delete(value)
        return self._result()

    def write(self, reference: str, fc: str, value: bool | int | float | str) -> str:
        """Try to write one attribute. Returns ``ok`` or the refusal, such as ``access-denied``."""
        lib = self._lib
        if isinstance(value, bool):
            made = lib.MmsValue_newBoolean(value)
        elif isinstance(value, int):
            made = lib.MmsValue_newIntegerFromInt32(value)
        elif isinstance(value, float):
            made = lib.MmsValue_newFloat(value)
        else:
            made = lib.MmsValue_newVisibleString(value.encode())
        return self._write(reference, fc, made)

    def _command(self, close: bool) -> int:
        lib = self._lib
        command = lib.MmsValue_createEmptyStructure(6)
        origin = lib.MmsValue_createEmptyStructure(2)
        lib.MmsValue_setElement(origin, 0, lib.MmsValue_newIntegerFromInt32(3))
        lib.MmsValue_setElement(origin, 1, lib.MmsValue_newOctetString(0, 64))
        lib.MmsValue_setElement(command, 0, lib.MmsValue_newBoolean(close))
        lib.MmsValue_setElement(command, 1, origin)
        lib.MmsValue_setElement(command, 2, lib.MmsValue_newUnsignedFromUint32(1))
        lib.MmsValue_setElement(command, 3, lib.MmsValue_newUtcTimeByMsTime(0))
        lib.MmsValue_setElement(command, 4, lib.MmsValue_newBoolean(False))
        lib.MmsValue_setElement(command, 5, lib.MmsValue_newBitString(2))
        return int(command)

    def operate(self, data_object: str, close: bool) -> str:
        """Try to operate a control object (a write to its ``Oper``). Returns the answer."""
        return self._write(f"{data_object}.Oper", "CO", self._command(close))

    def select(self, data_object: str, close: bool) -> str:
        """Try to select a control object with a value (``SBOw``). Returns the answer."""
        return self._write(f"{data_object}.SBOw", "CO", self._command(close))

    def set_active_setting_group(self, domain: str, group: int) -> str:
        """Try to change the active setting group. Returns the answer."""
        made = self._lib.MmsValue_newUnsignedFromUint32(group)
        return self._write(f"{domain}/LLN0.SGCB.ActSG", "SP", made)

    def edit_setting_group(self, domain: str, group: int) -> str:
        """Try to open a setting group for editing. Returns the answer."""
        made = self._lib.MmsValue_newUnsignedFromUint32(group)
        return self._write(f"{domain}/LLN0.SGCB.EditSG", "SP", made)

    def file_directory(self, name: str = "") -> str:
        """Ask for a file directory. Returns the answer."""
        found = self._lib.IedConnection_getFileDirectory(
            self._connection, self._error, name.encode()
        )
        result = self._result()
        if found:
            self._lib.LinkedList_destroyStatic(found)
        return result

    def get_file(self, name: str) -> str:
        """Try to fetch a file. Returns the answer."""
        handler = library.GetFileHandler(lambda *_: True)
        self._lib.IedConnection_getFile(self._connection, self._error, name.encode(), handler, None)
        return self._result()

    def delete_file(self, name: str) -> str:
        """Try to delete a file. Returns the answer."""
        self._lib.IedConnection_deleteFile(self._connection, self._error, name.encode())
        return self._result()

    def create_data_set(self, reference: str, members: tuple[str, ...]) -> str:
        """Try to create a data set. Returns the answer."""
        lib = self._lib
        items = lib.LinkedList_create()
        kept = [ctypes.create_string_buffer(m.encode()) for m in members]
        for item in kept:
            lib.LinkedList_add(items, ctypes.cast(item, ctypes.c_void_p))
        lib.IedConnection_createDataSet(self._connection, self._error, reference.encode(), items)
        lib.LinkedList_destroyStatic(items)
        return self._result()


class AccessError(RuntimeError):
    """The relay answered a read with an error instead of a value."""

    def __init__(self, code: int, name: str = "") -> None:
        """Keep the library's error *code* and, if known, its *name*."""
        super().__init__(name or f"data access error {code}")
        self.code, self.name = code, name
