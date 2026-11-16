"""ADC-PRO-002: one point, read over two protocols in one step, is one sample.

Every protocol server is a view of the same point database (SDD 8). The table
``PROTOCOLS`` names each protocol under test with a function that starts its
server on loopback and returns a reader. A reader answers a point map with the
value, after the scaling that protocol documents is undone, and the quality as
that protocol carries it; a protocol that has no quality on the wire, like a
Modbus register read, answers ``None`` for it. A new protocol is one more
entry in the table.

What is compared, for every point that two or more protocols serve:

- Value: every pair of protocols that serve the point, Modbus included, within
  the error the two encodings may add (``Protocol.relative`` and
  ``Protocol.absolute``).
- Quality: the pairs OPC UA with BACnet and OPC UA with SNMP, on every point
  the pair shares. No point is served by both BACnet and SNMP in the generic
  profile, so that pair is never compared; the test fails if one appears
  without being counted.
- Modbus is compared for value only. A register read has no quality.

How each protocol carries quality: OPC UA in the status code; BACnet in the
reliability property, with the fault flag set whenever it is not good; SNMP in
the parallel quality subtree. The point database produces ``good`` and
``stale`` only, and both are compared. BACnet has one reliability for
``uncertain`` and ``bad`` alike, so those two could not be told apart over it.
"""

import asyncio
from collections import Counter
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
from asyncua import ua
from asyncua.sync import Client as OpcUaClient
from bacpypes3.app import Application
from bacpypes3.ipv4.link import NormalLinkLayer
from bacpypes3.local.device import DeviceObject
from bacpypes3.pdu import Address, IPv4Address
from pymodbus.client import ModbusTcpClient
from pysnmp.hlapi.v3arch.asyncio import (
    USM_AUTH_HMAC192_SHA256,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    get_cmd,
)

from agentic_datacenter.core.io import PointValue
from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.net.bacnet import CONTROLLER_NETWORK, BacnetServer, BacnetView
from agentic_datacenter.net.maps import PointMap, protocol_maps
from agentic_datacenter.net.modbus import BASE, ModbusServer, ModbusView, decode
from agentic_datacenter.net.opcua import STATUS_OF_QUALITY, OpcUaServer, OpcUaView
from agentic_datacenter.net.snmp import (
    AUTH_KEY,
    QUALITY_CODE,
    SCALE,
    USER,
    SnmpAgent,
    SnmpView,
    quality_oid,
)
from agentic_datacenter.net.snmp import decode as snmp_decode
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[2]
#: What a protocol says about one point: the value, and the quality if it carries one.
type Sample = tuple[PointValue, str | None]
type Reader = Callable[[PointMap], Sample]
type Opened = tuple[Reader, Callable[[], None]]
#: The BACnet reliability a point of each quality is read with (ADR 0013).
QUALITY_OF_RELIABILITY = {"no-fault-detected": "good", "communication-failure": "stale"}


def open_modbus(kernel: Kernel, points: PointDatabase, maps: list[PointMap]) -> Opened:
    server = ModbusServer(ModbusView(kernel, points, maps))
    client = ModbusTcpClient("127.0.0.1", port=server.start("127.0.0.1", 0), timeout=5)
    assert client.connect()

    def read(m: PointMap) -> Sample:
        decl = points.declaration(m.tag)
        bits = m.object_type in ("coil", "discrete_input")
        count = 1 if bits else ModbusView.width(decl.kind, m.writable)
        call = {
            "coil": client.read_coils,
            "discrete_input": client.read_discrete_inputs,
            "input_register": client.read_input_registers,
            "holding_register": client.read_holding_registers,
        }[m.object_type]
        answer = call(int(m.address) - BASE[m.object_type], count=count, device_id=m.device_number)
        assert not answer.isError(), (m.tag, answer)
        return decode(answer.bits[:1] if bits else answer.registers, decl, m.writable), None

    def close() -> None:
        client.close()
        server.stop()

    return read, close


def open_opcua(kernel: Kernel, points: PointDatabase, maps: list[PointMap]) -> Opened:
    server = OpcUaServer(OpcUaView(kernel, points, maps))
    client = OpcUaClient(f"opc.tcp://127.0.0.1:{server.start('127.0.0.1', 0)}", timeout=10)
    client.connect()
    quality_of_status = {int(code): quality for quality, code in STATUS_OF_QUALITY.items()}

    def read(m: PointMap) -> Sample:
        # Not Node.read_value: it raises on any status that is not good.
        answer: ua.DataValue = client.read_attributes([client.get_node(str(m.address))])[0]
        assert answer.Value is not None and answer.StatusCode is not None, m.tag
        value: PointValue = answer.Value.Value
        return value, quality_of_status[int(answer.StatusCode.value)]

    def close() -> None:
        client.disconnect()
        server.stop()

    return read, close


def open_bacnet(kernel: Kernel, points: PointDatabase, maps: list[PointMap]) -> Opened:
    server = BacnetServer(BacnetView(kernel, points, maps))
    port = server.start("127.0.0.1", 0)
    loop = asyncio.new_event_loop()

    async def connect() -> tuple[Any, Any]:
        device = DeviceObject(
            objectIdentifier=("device", 4_000_002), objectName="cross", vendorIdentifier=999
        )
        app = Application.from_object_list([device])
        address = IPv4Address("127.0.0.1/32:0")
        link = NormalLinkLayer(address)
        app.nsap.bind(link, address=address)
        router = IPv4Address(f"127.0.0.1:{port}")
        await app.nsap.router_info_cache.update_path_info(None, router, {CONTROLLER_NETWORK})
        return app, link

    app, link = loop.run_until_complete(connect())

    def read(m: PointMap) -> Sample:
        decl = points.declaration(m.tag)
        station, obj = (
            Address(f"{CONTROLLER_NETWORK}:{m.device_number}"),
            f"{m.object_type},{m.address}",
        )

        def ask(prop: str) -> Any:
            return loop.run_until_complete(
                asyncio.wait_for(app.read_property(station, obj, prop), 5)
            )

        raw = ask("present-value")
        value: PointValue
        if decl.kind.startswith("binary"):
            value = str(raw) == "active"
        elif decl.kind == "enum_status":
            value = (decl.values or ())[int(raw) - 1]
        elif decl.kind == "counter":
            # A counter is served as a REAL; it stands for the whole number it holds.
            assert float(raw) == int(raw), m.tag
            value = int(raw)
        else:
            value = float(raw)
        quality = QUALITY_OF_RELIABILITY[str(ask("reliability"))]
        fault = bool(tuple(ask("status-flags"))[1])
        assert fault is (quality != "good"), (m.tag, "the fault flag and the reliability disagree")
        return value, quality

    def close() -> None:
        link.close()
        app.close()
        loop.run_until_complete(asyncio.sleep(0.05))
        loop.close()
        server.stop()

    return read, close


def open_snmp(kernel: Kernel, points: PointDatabase, maps: list[PointMap]) -> Opened:
    agent = SnmpAgent(SnmpView(kernel, points, maps))
    port = agent.start("127.0.0.1", 0)
    loop = asyncio.new_event_loop()
    engine = SnmpEngine()
    user = UsmUserData(USER, AUTH_KEY, authProtocol=USM_AUTH_HMAC192_SHA256)
    target = loop.run_until_complete(UdpTransportTarget.create(("127.0.0.1", port), 2, 0))
    quality_of_code = {code: quality for quality, code in QUALITY_CODE.items()}

    def read(m: PointMap) -> Sample:
        # One request for the value and its quality: one sample.
        oids = (str(m.address), quality_oid(str(m.address)))
        indication, status, _, binds = loop.run_until_complete(
            get_cmd(
                engine, user, target, ContextData(), *[ObjectType(ObjectIdentity(o)) for o in oids]
            )
        )
        assert indication is None and int(status) == 0, (m.tag, indication, status)
        assert tuple(str(name) for name, _ in binds) == oids, m.tag
        value = snmp_decode(int(binds[0][1]), points.declaration(m.tag))
        return value, quality_of_code[int(binds[1][1])]

    def close() -> None:
        engine.close_dispatcher()
        loop.close()
        agent.stop()

    return read, close


@dataclass(frozen=True)
class Protocol:
    """One protocol under test: its name in the maps and how to reach its server."""

    name: str
    open: Callable[[Kernel, PointDatabase, list[PointMap]], Opened]
    #: Whether a read over it says what the quality of the sample is.
    carries_quality: bool
    #: Relative error its encoding of an analog value may add (single precision: 2**-24).
    relative: float = 0.0
    #: Absolute error its encoding of an analog value may add (a scaled integer: half a step).
    absolute: float = 0.0


PROTOCOLS: tuple[Protocol, ...] = (
    Protocol("modbus", open_modbus, carries_quality=False, relative=1e-6, absolute=1e-6),
    Protocol("opcua", open_opcua, carries_quality=True),
    Protocol("bacnet", open_bacnet, carries_quality=True, relative=1e-6, absolute=1e-6),
    Protocol("snmp", open_snmp, carries_quality=True, absolute=0.5 / SCALE),
)
BY_NAME = {p.name: p for p in PROTOCOLS}
#: The pairs whose quality is compared; see the module docstring.
QUALITY_PAIRS = {("bacnet", "opcua"), ("opcua", "snmp")}


@dataclass
class Site:
    kernel: Kernel
    points: PointDatabase
    readers: dict[str, Reader]
    #: tag -> protocol name -> map, for every point that at least two protocols serve.
    shared: dict[str, dict[str, PointMap]]


@pytest.fixture(scope="module")
def site() -> Iterator[Site]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    kernel.run_for(5000)
    maps = protocol_maps(points)
    readers: dict[str, Reader] = {}
    closers: list[Callable[[], None]] = []
    by_tag: dict[str, dict[str, PointMap]] = {}
    try:
        for protocol in PROTOCOLS:
            own = [m for m in maps if m.protocol == protocol.name]
            assert own, protocol.name
            readers[protocol.name], close = protocol.open(kernel, points, own)
            closers.append(close)
            for m in own:
                by_tag.setdefault(m.tag, {})[protocol.name] = m
        shared = {tag: found for tag, found in by_tag.items() if len(found) >= 2}
        yield Site(kernel, points, readers, shared)
    finally:
        for close in closers:
            close()


def same(a: PointValue, b: PointValue, *protocols: str) -> bool:
    """Whether *a* and *b* are one value, given the encodings of *protocols*."""
    if isinstance(a, float) and isinstance(b, float):
        relative = sum(BY_NAME[name].relative for name in protocols)
        absolute = sum(BY_NAME[name].absolute for name in protocols)
        return abs(a - b) <= relative * max(abs(a), abs(b)) + absolute
    return a == b and type(a) is type(b)


@dataclass
class Compared:
    """How many points each pair of protocols was compared on."""

    value: Counter[tuple[str, str]]
    quality: Counter[tuple[str, str]]


def check_every_shared_point(site: Site, quality: str) -> Compared:
    """Read every shared point over each of its protocols without a step in between."""
    step = site.kernel.clock.step_count
    compared = Compared(Counter(), Counter())
    for tag, found in sorted(site.shared.items()):
        record = site.points.read(tag)
        assert record.quality == quality, tag
        samples = {name: site.readers[name](m) for name, m in found.items()}
        for name, (value, carried) in samples.items():
            assert same(value, record.value, name), (tag, name, value, record.value)
            if BY_NAME[name].carries_quality:
                assert carried == record.quality, (tag, name, carried)
            else:
                assert carried is None, (tag, name, carried)
        names = sorted(samples)
        for i, first in enumerate(names):
            for second in names[i + 1 :]:
                (a, quality_a), (b, quality_b) = samples[first], samples[second]
                assert same(a, b, first, second), (tag, first, second, a, b)
                compared.value[first, second] += 1
                if quality_a is not None and quality_b is not None:
                    assert quality_a == quality_b, (tag, first, second, quality_a, quality_b)
                    compared.quality[first, second] += 1
        assert any(carried is not None for _, carried in samples.values()), (
            f"{tag}: no protocol that serves it carries a quality"
        )
    assert site.kernel.clock.step_count == step, "every read was in the same step"
    assert set(compared.quality) == QUALITY_PAIRS, "the pairs the module docstring names"
    assert {pair for pair in compared.value if "modbus" in pair} == set(compared.value) - set(
        compared.quality
    ), "Modbus, and only Modbus, is compared for value alone"
    return compared


def served(site: Site, protocol: str) -> int:
    return sum(protocol in found for found in site.shared.values())


@pytest.mark.req("ADC-PRO-002")
def test_a_point_reads_the_same_over_every_protocol_that_serves_it(site: Site) -> None:
    assert len(site.shared) > 600
    kinds = {site.points.read(tag).kind for tag in site.shared}
    assert kinds >= {"analog_in", "analog_setting", "binary_in", "binary_cmd", "counter"}
    compared = check_every_shared_point(site, "good")
    assert sum(compared.value.values()) >= len(site.shared)
    # OPC UA serves every mapped point, so each other protocol meets it on all of its own.
    assert served(site, "opcua") == len(site.shared)
    assert compared.quality["bacnet", "opcua"] == served(site, "bacnet") > 300
    assert compared.quality["opcua", "snmp"] == served(site, "snmp") == 21
    assert compared.value["modbus", "opcua"] == served(site, "modbus") > 300
    assert compared.value["bacnet", "modbus"] > 0 and compared.value["modbus", "snmp"] == 21


@pytest.mark.req("ADC-PRO-002")
def test_a_stale_point_reads_the_same_over_every_protocol_that_serves_it(site: Site) -> None:
    #: One point for each protocol that carries a quality, and one that Modbus serves too.
    tags = {
        "cooling.tes[TES-1].charge_pct": {"modbus", "opcua"},
        "cooling.chw_plant[CHW].chws_c": {"bacnet", "opcua"},
        "electrical.ups[A].soc_pct": {"modbus", "opcua", "snmp"},
    }
    held = {}
    for tag, protocols in tags.items():
        assert set(site.shared[tag]) == protocols, tag
        held[tag] = site.points.read(tag).value
    site.points.set_link(False)
    try:
        site.kernel.run_for(4000)
        for tag in tags:
            assert site.points.read(tag).quality == "stale"
            for name, m in site.shared[tag].items():
                value, carried = site.readers[name](m)
                assert same(value, held[tag], name), (
                    name,
                    "the last value polled, not the live one",
                )
                assert carried == ("stale" if BY_NAME[name].carries_quality else None), (tag, name)
        compared = check_every_shared_point(site, "stale")
        assert compared.quality["bacnet", "opcua"] == served(site, "bacnet")
        assert compared.quality["opcua", "snmp"] == served(site, "snmp")
    finally:
        site.points.set_link(True)
    site.kernel.run_for(1000)
    check_every_shared_point(site, "good")
