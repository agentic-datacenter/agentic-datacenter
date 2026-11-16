"""The Modbus/TCP view of the point database (SDD 8, ADR 0012).

One Modbus device per mapped module instance. A read is answered with what
the point database holds at that moment; a write is accepted only at a
register the map marks writable and only with a value the point's declaration
allows. Everything else gets the exception a device would give: 1 for a
function it does not serve, 2 for an address it does not have or will not let
be written, 3 for a value it will not take.

Encoding: an analog value is IEEE 754 single precision in two registers, high
word first; a counter is an unsigned 32-bit integer in two registers; an
enumerated status is its index in one register (two when it is writable).

The server answers at once: the response latency of section 8.4 is not
modelled here. The device does not learn who is asking through the library's
interface, so a refused write is recorded without a source address; the
conduit, which owns the connection, records that.
"""

from __future__ import annotations

import asyncio
import socket
import struct
import threading
from collections.abc import Sequence
from typing import Any

from pymodbus.constants import ExcCodes
from pymodbus.server import ModbusTcpServer
from pymodbus.simulator import DataType, SimData, SimDevice

from agentic_datacenter.core.io import PointDecl, PointValue
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.net.guard import check_bind
from agentic_datacenter.net.maps import PointMap
from agentic_datacenter.supervisory.points import PointDatabase

#: First register number of each table, as the maps write them.
BASE = {"coil": 1, "discrete_input": 10001, "input_register": 30001, "holding_register": 40001}
_TABLE_OF_FUNCTION = {
    1: "coil", 5: "coil", 15: "coil", 2: "discrete_input", 4: "input_register",
    3: "holding_register", 6: "holding_register", 16: "holding_register",
}  # fmt: skip
_BITS = ("coil", "discrete_input")
_ORDER = ("coil", "discrete_input", "holding_register", "input_register")


def encode(value: PointValue, decl: PointDecl, writable: bool) -> list[int]:
    """Return *value* as register words (or one bit) for the wire."""
    if decl.kind.startswith("binary"):
        return [1 if value else 0]
    if decl.kind == "enum_status":
        index = (decl.values or ()).index(str(value))
        return [index >> 16, index & 0xFFFF] if writable else [index]
    if decl.kind == "counter":
        number = int(value) & 0xFFFFFFFF
        return [number >> 16, number & 0xFFFF]
    return list(struct.unpack(">HH", struct.pack(">f", float(value))))


def decode(raw: Sequence[int | bool], decl: PointDecl, writable: bool) -> PointValue:
    """Return the value that register words *raw* stand for.

    Raises:
        ValueError: If the words are not a value of this point.
    """
    if decl.kind.startswith("binary"):
        return bool(raw[0])
    if decl.kind == "enum_status":
        index = (int(raw[0]) << 16 | int(raw[1])) if writable else int(raw[0])
        values = decl.values or ()
        if not 0 <= index < len(values):
            raise ValueError(f"{index} is not one of the {len(values)} states")
        return values[index]
    if decl.kind == "counter":
        return int(raw[0]) << 16 | int(raw[1])
    value = struct.unpack(">f", struct.pack(">HH", int(raw[0]), int(raw[1])))[0]
    return float(value)


class ModbusView:
    """Every Modbus device of the facility, as views of the point database."""

    def __init__(self, kernel: Kernel, points: PointDatabase, maps: Sequence[PointMap]) -> None:
        """Build the device tables from the Modbus *maps*."""
        self._kernel, self._points = kernel, points
        self.lock = threading.Lock()
        self._violations: list[dict[str, JsonValue]] = []
        #: unit id -> table -> list of (offset, width, map)
        self._tables: dict[int, dict[str, list[tuple[int, int, PointMap]]]] = {}
        self._names: dict[int, str] = {}
        for m in maps:
            if m.protocol != "modbus":
                continue
            width = self.width(points.declaration(m.tag).kind, m.writable)
            if m.object_type in _BITS:
                width = 1
            tables = self._tables.setdefault(m.device_number, {name: [] for name in _ORDER})
            tables[m.object_type].append((int(m.address) - BASE[m.object_type], width, m))
            self._names[m.device_number] = m.device

    @staticmethod
    def width(kind: str, writable: bool) -> int:
        """Return how many registers a point of *kind* takes."""
        if kind.startswith("binary"):
            return 1
        if kind == "enum_status":
            return 2 if writable else 1
        return 2

    # -- what the library calls --------------------------------------------------------------

    def _size(self, unit: int, table: str) -> int:
        entries = self._tables[unit][table]
        return max((offset + width for offset, width, _ in entries), default=0)

    def _refresh(self, unit: int, table: str, registers: list[int]) -> None:
        for offset, _, m in self._tables[unit][table]:
            decl = self._points.declaration(m.tag)
            words = encode(self._points.read(m.tag).value, decl, m.writable)
            if table in _BITS:
                word, bit = divmod(offset, 16)
                registers[word] = (registers[word] & ~(1 << bit)) | (words[0] << bit)
            else:
                registers[offset : offset + len(words)] = words

    def _refuse(self, unit: int, function: int, address: int, tag: str, why: str) -> None:
        entry: dict[str, JsonValue] = {
            "time_ms": self._kernel.clock.now_ms, "device": self._names[unit], "unit": unit,
            "function": function, "address": address, "tag": tag, "reason": why,
        }  # fmt: skip
        self._violations.append(entry)
        self._kernel.events.publish("net.device_violation", entry)

    def _write(
        self, unit: int, function: int, table: str, address: int, values: Sequence[int | bool]
    ) -> ExcCodes | None:
        by_offset = {offset: (width, m) for offset, width, m in self._tables[unit][table]}
        position, planned = address, []
        while position < address + len(values):
            found = by_offset.get(position)
            if found is None or position + found[0] > address + len(values):
                self._refuse(unit, function, position, "", "no whole point at this address")
                return ExcCodes.ILLEGAL_ADDRESS
            width, m = found
            if not m.writable:
                self._refuse(unit, function, position, m.tag, "the point is read-only")
                return ExcCodes.ILLEGAL_ADDRESS
            decl = self._points.declaration(m.tag)
            raw = values[position - address : position - address + width]
            try:
                value = decode(raw, decl, m.writable)
            except ValueError:
                return ExcCodes.ILLEGAL_VALUE
            if decl.problem_with(value) is not None:
                return ExcCodes.ILLEGAL_VALUE
            planned.append((m.tag, value))
            position += width
        for tag, value in planned:
            self._points.write_through(tag, value)
        return None

    async def _action(
        self,
        unit: int,
        function: int,
        start: int,
        address: int,
        count: int,
        registers: list[int],
        values: list[int] | list[bool] | None,
    ) -> ExcCodes | None:
        del start, count
        table = _TABLE_OF_FUNCTION.get(function)
        if table is None:
            return ExcCodes.ILLEGAL_FUNCTION
        with self.lock:
            if values is not None:
                refused = self._write(unit, function, table, address, values)
                if refused is not None:
                    return refused
            self._refresh(unit, table, registers)
        return None

    # -- for whoever serves it -----------------------------------------------------------------

    def devices(self) -> list[SimDevice]:
        """Return one library device per Modbus device of the facility."""
        out = []
        for unit in sorted(self._tables):
            blocks = []
            for table in _ORDER:
                size = max(1, self._size(unit, table))
                kind = DataType.BITS if table in _BITS else DataType.REGISTERS
                blocks.append([SimData(address=0, count=size, values=0, datatype=kind)])

            async def action(
                function: int,
                start: int,
                address: int,
                count: int,
                registers: list[int],
                values: list[int] | list[bool] | None,
                unit: int = unit,
            ) -> ExcCodes | None:
                return await self._action(unit, function, start, address, count, registers, values)

            out.append(SimDevice(id=unit, simdata=tuple(blocks), action=action))  # type: ignore[arg-type]
        return out

    def violations(self) -> list[dict[str, JsonValue]]:
        """Return every refused write so far."""
        return [dict(entry) for entry in self._violations]


class ModbusServer:
    """Serves a :class:`ModbusView` on a TCP port, from a thread of its own."""

    def __init__(self, view: ModbusView) -> None:
        """Create the server; nothing is bound until :meth:`start`."""
        self.view = view
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._server: Any = None

    def start(self, host: str, port: int, allow_external: bool = False) -> int:
        """Bind *host*:*port* (0 picks a free port) and serve. Return the port.

        Raises:
            ExternalAddressError: If the address is outside the simulator's own
                networks and *allow_external* is not set (ADC-SAF-001).
        """
        check_bind(host, allow_external=allow_external)
        if port == 0:
            with socket.socket() as probe:
                probe.bind((host, 0))
                port = int(probe.getsockname()[1])
        failed: list[BaseException] = []

        def run() -> None:
            loop = asyncio.new_event_loop()
            self._loop = loop

            async def serve() -> None:
                # The library wants a running loop when the server is created.
                self._server = ModbusTcpServer(self.view.devices(), address=(host, port))
                await self._server.serve_forever()

            try:
                loop.run_until_complete(serve())
            except asyncio.CancelledError:
                pass
            except BaseException as exc:  # noqa: BLE001 - reported to the caller below
                failed.append(exc)
            finally:
                loop.close()

        self._thread = threading.Thread(target=run, name="agentic-datacenter-modbus", daemon=True)
        self._thread.start()
        pause = threading.Event()
        for _ in range(200):
            if failed:
                raise RuntimeError(f"the Modbus server did not start: {failed[0]}")
            with socket.socket() as probe:
                probe.settimeout(0.2)
                if probe.connect_ex((host, port)) == 0:
                    return port
            pause.wait(0.05)
        raise RuntimeError("the Modbus server did not start listening")

    def stop(self) -> None:
        """Stop serving and release the port."""
        if self._loop is None or self._server is None or self._thread is None:
            return
        asyncio.run_coroutine_threadsafe(self._server.shutdown(), self._loop).result(10.0)
        self._thread.join(10.0)
        self._thread = self._loop = self._server = None
