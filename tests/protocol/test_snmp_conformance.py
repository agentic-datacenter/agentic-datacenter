"""ADC-PRO-001 for SNMP: the agent is a read-only view of the point database (ADR 0014)."""

import asyncio
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pysnmp.hlapi.v3arch.asyncio import (
    USM_AUTH_HMAC192_SHA256,
    CommunityData,
    ContextData,
    ObjectIdentity,
    ObjectType,
    SnmpEngine,
    UdpTransportTarget,
    UsmUserData,
    bulk_cmd,
    get_cmd,
    next_cmd,
    set_cmd,
    walk_cmd,
)
from pysnmp.proto import rfc1905
from pysnmp.proto.rfc1902 import Integer32

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.net.guard import ExternalAddressError
from agentic_datacenter.net.maps import SNMP_BASE, PointMap, protocol_maps
from agentic_datacenter.net.snmp import (
    AUTH_KEY,
    QUALITY_CODE,
    SCALE,
    USER,
    SnmpAgent,
    SnmpView,
    decode,
    quality_oid,
)
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[2]
SOC = "electrical.ups[A].soc_pct"
MODE = "electrical.ups[A].mode"
ALARM = "electrical.ups[A].on_battery_alarm"
NOT_WRITABLE = 17


def key(oid: str) -> tuple[int, ...]:
    return tuple(int(arc) for arc in oid.split("."))


class Client:
    """A manager on loopback: one event loop and one engine for the whole module."""

    def __init__(self, port: int) -> None:
        self.loop = asyncio.new_event_loop()
        self.engine = SnmpEngine()
        self.port = port
        self.user = UsmUserData(USER, AUTH_KEY, authProtocol=USM_AUTH_HMAC192_SHA256)
        self.target = self.run(UdpTransportTarget.create(("127.0.0.1", port), 2, 0))

    def run(self, coroutine: Any) -> Any:
        return self.loop.run_until_complete(coroutine)

    def call(self, command: Any, *args: Any, user: Any = None) -> Any:
        """Return (error indication, error status, error index, [(oid, value)])."""
        indication, status, index, binds = self.run(
            command(self.engine, user or self.user, self.target, ContextData(), *args)
        )
        return indication, int(status), int(index), [(str(name), value) for name, value in binds]

    def get(self, *oids: str, user: Any = None) -> Any:
        return self.call(get_cmd, *[ObjectType(ObjectIdentity(oid)) for oid in oids], user=user)

    def one(self, oid: str) -> Any:
        """Return the value at *oid*, which must be answered without an error."""
        indication, status, _, binds = self.get(oid)
        assert indication is None and status == 0, (oid, indication, status)
        assert binds[0][0] == oid
        return binds[0][1]

    def next(self, oid: str) -> Any:
        indication, status, _, binds = self.call(next_cmd, ObjectType(ObjectIdentity(oid)))
        assert indication is None and status == 0, (oid, indication, status)
        return binds[0]

    def walk(self, root: str) -> list[tuple[str, Any]]:
        async def collect() -> list[tuple[str, Any]]:
            found = []
            async for indication, status, _, binds in walk_cmd(
                self.engine, self.user, self.target, ContextData(),
                ObjectType(ObjectIdentity(root)), lexicographicMode=False,
            ):  # fmt: skip
                assert indication is None and int(status) == 0, (indication, status)
                found += [(str(name), value) for name, value in binds]
            return found

        return list(self.run(collect()))

    def close(self) -> None:
        self.engine.close_dispatcher()
        self.loop.close()


@pytest.fixture(scope="module")
def site() -> Iterator[tuple[Kernel, Any, PointDatabase, list[PointMap], SnmpAgent, Client]]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    kernel.run_for(5000)
    maps = [m for m in protocol_maps(points) if m.protocol == "snmp"]
    agent = SnmpAgent(SnmpView(kernel, points, maps))
    port = agent.start("127.0.0.1", 0)
    client = Client(port)
    yield kernel, plant, points, maps, agent, client
    client.close()
    agent.stop()


def find(maps: list[PointMap], tag: str) -> PointMap:
    return next(m for m in maps if m.tag == tag)


def expected_oids(maps: list[PointMap]) -> list[str]:
    values = [str(m.address) for m in maps]
    return sorted(values + [quality_oid(oid) for oid in values], key=key)


@pytest.mark.req("ADC-PRO-001")
def test_every_mapped_point_reads_as_the_point_database_holds_it(site: Any) -> None:
    _, _, points, maps, _, client = site
    assert len(maps) == 21, "seven points on each of three UPS"
    assert {m.device.split("[")[0] for m in maps} == {"electrical.ups"}
    for m in maps:
        record = points.read(m.tag)
        decl = points.declaration(m.tag)
        answer = client.one(str(m.address))
        assert answer.tagSet == Integer32.tagSet, (m.tag, type(answer))
        value = decode(int(answer), decl)
        if isinstance(record.value, float):
            # Scaling, stated: an analog value is sent as round(value * 1000).
            assert int(answer) == round(record.value * 1000), m.tag
            assert value == pytest.approx(record.value, abs=0.5 / SCALE), m.tag
        else:
            assert value == record.value, m.tag
        quality = client.one(quality_oid(str(m.address)))
        assert int(quality) == QUALITY_CODE[record.quality] == 1, m.tag


@pytest.mark.req("ADC-PRO-001")
def test_the_encoding_is_the_one_the_decision_record_states(site: Any) -> None:
    _, _, points, maps, _, client = site
    assert SCALE == 1000
    assert QUALITY_CODE == {"good": 1, "uncertain": 2, "bad": 3, "stale": 4}
    assert points.read(SOC).value == 100.0
    assert int(client.one(str(find(maps, SOC).address))) == 100_000
    assert points.read(MODE).value == "ONLINE", "the first of the declared states"
    assert int(client.one(str(find(maps, MODE).address))) == 1
    assert points.read(ALARM).value is False
    assert int(client.one(str(find(maps, ALARM).address))) == 2
    several = client.get(*[str(find(maps, tag).address) for tag in (SOC, MODE, ALARM)])
    assert [int(value) for _, value in several[3]] == [100_000, 1, 2], "one request, three values"


@pytest.mark.req("ADC-PRO-001")
def test_a_value_that_changes_in_the_plant_changes_on_the_wire(site: Any) -> None:
    kernel, plant, points, maps, _, client = site
    plant.module("electrical.ups", "B").inject("set_soc", pct=42.0)
    kernel.run_for(1000)
    m = find(maps, "electrical.ups[B].soc_pct")
    held = points.read(m.tag).value
    assert held == pytest.approx(42.0, abs=1.0)
    assert int(client.one(str(m.address))) == round(held * SCALE)


@pytest.mark.req("ADC-PRO-001")
def test_a_walk_returns_exactly_the_mapped_identifiers_in_order(site: Any) -> None:
    _, _, _, maps, agent, client = site
    expected = expected_oids(maps)
    assert len(expected) == 42 and all(oid.startswith(SNMP_BASE + ".") for oid in expected)
    walked = [oid for oid, _ in client.walk(SNMP_BASE)]
    assert walked == expected
    assert agent.view.oids() == expected
    assert [oid for oid, _ in client.walk("1.3.6.1")] == expected, "nothing else is served"
    one_device = f"{SNMP_BASE}.{maps[0].device_number}"
    assert [oid for oid, _ in client.walk(one_device)] == [
        str(m.address) for m in maps if m.device == maps[0].device
    ]


@pytest.mark.req("ADC-PRO-001")
def test_getbulk_returns_the_same_sequence_and_then_end_of_view(site: Any) -> None:
    _, _, _, maps, _, client = site
    expected = expected_oids(maps)
    indication, status, _, binds = client.call(
        bulk_cmd, 0, 50, ObjectType(ObjectIdentity(SNMP_BASE))
    )
    assert indication is None and status == 0
    assert [oid for oid, _ in binds[:42]] == expected
    assert len(binds) > 42 and all(
        value.tagSet == _exception("endOfMibView") for _, value in binds[42:]
    )


def _exception(name: str) -> Any:
    return {
        "noSuchObject": rfc1905.NoSuchObject.tagSet,
        "noSuchInstance": rfc1905.NoSuchInstance.tagSet,
        "endOfMibView": rfc1905.EndOfMibView.tagSet,
    }[name]


@pytest.mark.req("ADC-PRO-001")
def test_an_identifier_that_is_not_served_gets_the_right_exception(site: Any) -> None:
    _, _, _, maps, _, client = site
    soc = str(find(maps, SOC).address)
    device = f"{SNMP_BASE}.{find(maps, SOC).device_number}"
    last = expected_oids(maps)[-1]
    for oid in (f"{SNMP_BASE}.9999.1.0", f"{device}.99.0", SNMP_BASE, device, "1.3.6.1.2.1.1.1.0"):
        assert client.one(oid).tagSet == _exception("noSuchObject"), oid
    for oid in (soc[: -len(".0")], soc[: -len(".0")] + ".1", soc + ".0"):
        assert client.one(oid).tagSet == _exception("noSuchInstance"), oid
    for oid in (quality_oid(soc)[: -len(".0")], quality_oid(soc)[: -len(".0")] + ".7"):
        assert client.one(oid).tagSet == _exception("noSuchInstance"), oid
    for oid in (last, f"{SNMP_BASE}.9999", "1.3.6.1.5"):
        assert client.next(oid)[1].tagSet == _exception("endOfMibView"), oid
    assert client.next("1.3")[0] == expected_oids(maps)[0]
    assert client.next(soc[: -len(".0")])[0] == soc, "the instance follows its object"


@pytest.mark.req("ADC-PRO-001")
def test_a_set_is_refused_as_not_writable_and_recorded(site: Any) -> None:
    kernel, _, points, maps, agent, client = site
    soc = find(maps, SOC)
    before = points.read(SOC).value
    seen: list[Any] = []
    kernel.events.subscribe("net.device_violation", seen.append)
    indication, status, index, _ = client.call(
        set_cmd, ObjectType(ObjectIdentity(str(soc.address)), Integer32(5000))
    )
    assert indication is None
    assert status == NOT_WRITABLE and index == 1
    assert points.read(SOC).value == before, "nothing was written"
    violations = agent.view.violations()
    assert violations and violations[-1]["tag"] == SOC
    assert violations[-1]["device"] == soc.device and violations[-1]["unit"] == soc.device_number
    assert violations[-1]["function"] == "set" and violations[-1]["address"] == soc.address
    assert str(violations[-1]["source"]).startswith("127.0.0.1:")
    assert seen and seen[-1].payload == violations[-1]
    for oid in (quality_oid(str(soc.address)), f"{SNMP_BASE}.9999.1.0"):
        _, status, index, _ = client.call(set_cmd, ObjectType(ObjectIdentity(oid), Integer32(1)))
        assert status == NOT_WRITABLE and index == 1, oid
    assert agent.view.violations()[-1]["tag"] == "", "an identifier outside the map has no point"
    assert len(agent.view.violations()) == len(violations) + 2


@pytest.mark.req("ADC-PRO-001")
def test_only_the_authenticated_snmpv3_user_is_answered(site: Any) -> None:
    _, _, _, maps, _, client = site
    oid = str(find(maps, SOC).address)
    wrong_key = UsmUserData(USER, "not-the-right-key", authProtocol=USM_AUTH_HMAC192_SHA256)
    for user in (wrong_key, UsmUserData(USER), UsmUserData("somebody-else")):
        indication, _, _, binds = client.get(oid, user=user)
        assert indication is not None, "no data without the user's key"
        assert not [value for _, value in binds if value.tagSet == Integer32.tagSet]
    fast = client.run(UdpTransportTarget.create(("127.0.0.1", client.port), 0.5, 0))
    for community in (CommunityData("public", mpModel=1), CommunityData("public", mpModel=0)):
        indication, _, _, _ = client.run(
            get_cmd(client.engine, community, fast, ContextData(), ObjectType(ObjectIdentity(oid)))
        )
        assert "timeout" in str(indication), "SNMPv1 and SNMPv2c are not answered"
    assert int(client.one(oid)) > 0, "and the agent still answers its user"


@pytest.mark.req("ADC-PRO-001")
def test_a_stale_sample_reads_stale_with_the_value_last_held(site: Any) -> None:
    kernel, plant, points, maps, _, client = site
    m = find(maps, "electrical.ups[C].soc_pct")
    held = points.read(m.tag).value
    points.set_link(False)
    try:
        plant.module("electrical.ups", "C").inject("set_soc", pct=10.0)
        kernel.run_for(5000)
        record = points.read(m.tag)
        assert record.quality == "stale" and record.value == held
        assert int(client.one(quality_oid(str(m.address)))) == QUALITY_CODE["stale"] == 4
        assert int(client.one(str(m.address))) == round(held * SCALE)
    finally:
        points.set_link(True)
        plant.module("electrical.ups", "C").inject("set_soc", pct=100.0)
        kernel.run_for(1000)
    assert int(client.one(quality_oid(str(m.address)))) == 1


def test_the_view_walks_in_numeric_order_without_a_socket(site: Any) -> None:
    kernel, _, points, maps, _, _ = site
    view = SnmpView(kernel, points, protocol_maps(points))
    expected = expected_oids(maps)
    assert view.oids() == expected, "maps of other protocols are ignored"
    walked, at = [], "0"
    while (answer := view.get_next(at)).syntax != "endOfMibView":
        walked.append(answer.oid)
        at = answer.oid
    assert walked == expected
    assert answer.oid == expected[-1] and answer.value is None
    soc = str(find(maps, SOC).address)
    assert (view.get(soc).syntax, view.get(soc).value) == ("Integer32", 100_000)
    assert view.get(f"{SNMP_BASE}.9999.1.0").syntax == "noSuchObject"
    assert view.get(soc[: -len(".0")]).syntax == "noSuchInstance"
    assert view.get_next(f"{SNMP_BASE}.9").oid == expected[21]
    # Arc by arc as numbers: a text sort would put 10.1 first and 9.10 before 9.2.
    spread = [
        PointMap(SOC, "snmp", "Z1-PWR-A", "forged", int(device), "scalar", f"{SNMP_BASE}.{arcs}",
                 False)
        for arcs in ("10.1.0", "9.10.0", "9.2.0")
        for device in [arcs.split(".")[0]]
    ]  # fmt: skip
    ordered = SnmpView(kernel, points, spread)
    assert ordered.oids()[3:] == [f"{SNMP_BASE}.{arcs}" for arcs in ("9.2.0", "9.10.0", "10.1.0")]
    assert ordered.get_next(f"{SNMP_BASE}.9.2.0").oid == f"{SNMP_BASE}.9.10.0"
    assert ordered.get_next(f"{SNMP_BASE}.9.10.0").oid == f"{SNMP_BASE}.10.1.0"
    assert view.set(soc, source="test") == "notWritable"
    assert view.violations()[-1]["source"] == "test"


def test_protection_and_life_safety_are_not_reachable(site: Any) -> None:
    kernel, _, points, maps, agent, client = site
    served = {m.tag for m in maps}
    assert not [t for t in served if t.startswith(("life_safety[", "security["))]
    assert not [m for m in maps if m.zone == "Z0-PROT" or m.writable]
    assert len(agent.view.oids()) == 2 * len(maps)
    protected = next(t for t in points.tags() if points.read(t).zone == "Z0-PROT")
    command = "electrical.power_train[A].gen_brk_close_cmd"
    assert points.read(command).tier == "T0"
    for tag in (protected, command):
        forged = PointMap(
            tag, "snmp", points.read(tag).zone, "forged", 900, "scalar", f"{SNMP_BASE}.900.1.0",
            False,
        )  # fmt: skip
        with pytest.raises(ValueError, match="has no protocol map"):
            SnmpView(kernel, points, [*maps, forged])
    assert client.one(f"{SNMP_BASE}.900.1.0").tagSet == _exception("noSuchObject")


@pytest.mark.req("ADC-SAF-001")
def test_the_agent_refuses_to_bind_outside_the_simulators_own_networks(site: Any) -> None:
    _, _, _, _, agent, _ = site
    other = SnmpAgent(agent.view)
    with pytest.raises(ExternalAddressError):
        other.start("0.0.0.0", 0)  # noqa: S104
    with pytest.raises(ExternalAddressError):
        other.start("192.0.2.10", 10161)
    other.stop()


def test_the_agent_can_be_stopped_and_started_again_on_its_port(site: Any) -> None:
    _, _, _, maps, agent, _ = site
    other = SnmpAgent(agent.view)
    port = other.start("localhost", 0)
    with pytest.raises(RuntimeError, match="already serving"):
        other.start("127.0.0.1", 0)
    with pytest.raises(OSError, match="in use"):
        SnmpAgent(agent.view).start("127.0.0.1", port)
    other.stop()
    other.stop()
    assert other.start("127.0.0.1", port) == port
    again = Client(port)
    assert int(again.one(str(find(maps, SOC).address))) > 0
    again.close()
    other.stop()
