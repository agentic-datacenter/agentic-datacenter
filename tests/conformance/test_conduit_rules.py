"""ADC-NET-002, -003 and -004: what a conduit passes, what happens when it refuses."""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.net.maps import PointMap, protocol_maps
from agentic_datacenter.net.virtual_net import READ, WRITE, Request, VirtualNetwork, build_network
from agentic_datacenter.supervisory.logs import LogIntegrityError
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[2]
CHWS = "cooling.chw_plant[CHW].chws_sp_c"
CH1_STATE = "cooling.chw_plant[CHW].ch1_state"
TEST_START = "electrical.genset[A].test_start_request"
TDEN = "electrical.power_train[A].tden_s"


def facility() -> tuple[Kernel, PointDatabase, list[PointMap], VirtualNetwork]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    return kernel, points, protocol_maps(points), build_network(kernel, plant, points)


KERNEL, POINTS, MAPS, NET = facility()


def find(tag: str, protocol: str) -> PointMap:
    return next(m for m in MAPS if m.tag == tag and m.protocol == protocol)


def ask(m: PointMap, operation: str, host: str = "bms", **changes: Any) -> Any:
    fields: dict[str, Any] = {
        "source_zone": "Z2-SUP", "source_host": host, "destination_zone": m.zone,
        "destination_host": m.device, "protocol": m.protocol, "operation": operation,
        "object_type": m.object_type, "address": m.address,
    }  # fmt: skip
    return NET.request(Request(**{**fields, **changes}))


# --- maps ----------------------------------------------------------------------------------


@pytest.mark.req("ADC-NET-004")
def test_protection_and_life_safety_have_no_protocol_map() -> None:
    """ADR 0010: nothing in Z0-PROT is mapped, and no T0 command or setting anywhere."""
    mapped = {m.tag for m in MAPS}
    for tag in POINTS.tags():
        record = POINTS.read(tag)
        if record.zone == "Z0-PROT":
            assert tag not in mapped, tag
        if record.tier == "T0" and record.kind in ("binary_cmd", "analog_setting"):
            assert tag not in mapped, tag
    assert not [m for m in MAPS if m.tag.startswith(("life_safety[", "security["))]
    assert "electrical.power_train[A].gen_brk_close_cmd" not in mapped


@pytest.mark.req("ADC-NET-004")
def test_no_t0_or_t1_point_is_mapped_writable() -> None:
    for m in MAPS:
        if m.writable:
            assert POINTS.read(m.tag).tier in ("T2", "T3"), m.tag
    writable = {m.tag for m in MAPS if m.writable}
    assert {CHWS, TEST_START, "fuel[FUEL].transfer_enable"} <= writable
    assert TDEN not in writable and find(TDEN, "modbus").object_type == "holding_register"


def test_maps_follow_the_device_table_and_do_not_collide() -> None:
    assert find(CHWS, "bacnet").object_type == "analog-value"
    assert find(CH1_STATE, "bacnet").object_type == "multi-state-value"
    assert find(TEST_START, "modbus").object_type == "coil"
    assert {m.protocol for m in MAPS if m.device == "electrical.ups[A]"} == {
        "snmp", "modbus", "opcua",
    } - {"opcua"} | {"snmp", "modbus"}  # fmt: skip
    assert find("cooling.pod[01].supply_air_c", "modbus").writable is False
    assert find(CHWS, "opcua").address == f"ns=2;s={CHWS}" and not find(CHWS, "opcua").writable
    seen: set[tuple[str, str, str, int | str]] = set()
    for m in MAPS:
        key = (m.device, m.protocol, m.object_type, m.address)
        if m.protocol != "opcua":
            assert key not in seen, key
            seen.add(key)
    assert protocol_maps(POINTS) == MAPS, "the same facility gives the same maps"


# --- conduit C1 ------------------------------------------------------------------------------


@pytest.mark.req("ADC-NET-002")
def test_c1_passes_only_allowlisted_device_operation_and_address() -> None:
    setpoint, state = find(CHWS, "bacnet"), find(CH1_STATE, "bacnet")
    assert ask(setpoint, READ).allowed and ask(state, READ).allowed
    assert ask(setpoint, WRITE, host="command-service").allowed
    refused = {
        "another host": ask(setpoint, READ, host="operator-laptop"),
        "write from a reader": ask(setpoint, WRITE, host="bms"),
        "write to a status": ask(state, WRITE, host="command-service"),
        "another protocol": ask(setpoint, READ, protocol="modbus"),
        "another address": ask(setpoint, READ, address=9999),
        "another object type": ask(setpoint, READ, object_type="file"),
        "another device": ask(setpoint, READ, destination_host="cooling.chw_plant[NOPE]"),
        "the device in another zone": ask(setpoint, READ, destination_zone="Z1-FUEL"),
    }
    for why, answer in refused.items():
        assert not answer.allowed and answer.conduit == "C1", why
    assert "command service only" in refused["write from a reader"].rule
    assert "read-only" in refused["write to a status"].rule


@pytest.mark.req("ADC-NET-002")
def test_only_the_generator_test_start_is_writable_in_a_power_zone() -> None:
    power = [m for m in MAPS if m.zone == "Z1-PWR-A" and m.protocol != "opcua"]
    # The electrical room unit of the train sits in the same zone (zone_model.md, section 6).
    assert {m.tag for m in power if m.writable} == {
        TEST_START,
        "cooling.eroom[A].return_air_sp_c",
    }
    assert ask(find(TEST_START, "modbus"), WRITE, host="command-service").allowed
    assert not ask(find(TDEN, "modbus"), WRITE, host="command-service").allowed


@pytest.mark.req("ADC-NET-002")
def test_the_other_conduits_carry_what_the_zone_model_says() -> None:
    def go(*fields: Any, **more: Any) -> bool:
        return bool(NET.request(Request(*fields, **more)).allowed)

    assert go("Z2-SUP", "opcua-server", "Z3-DMZ", "historian-replica", "opcua")
    assert not go("Z3-DMZ", "historian-replica", "Z2-SUP", "opcua-server", "opcua")
    assert go("Z4-ENT", "laptop", "Z3-DMZ", "read-api", "https", READ)
    assert not go("Z4-ENT", "laptop", "Z3-DMZ", "read-api", "https", WRITE)
    assert go("Z3-DMZ", "gate", "Z2-SUP", "command-service", "https", WRITE)
    assert not go("Z3-DMZ", "data-collector", "Z2-SUP", "command-service", "https", WRITE)
    assert not go("Z3-DMZ", "gate", "Z2-SUP", "bms", "https", WRITE)
    assert go("Z0-PROT", "facp", "Z2-SUP", "bms", "contact", READ)
    assert not go("Z0-PROT", "facp", "Z2-SUP", "bms", "contact", WRITE)
    assert go("Z2-SEC", "acs", "Z2-SUP", "bms", "events")
    assert not go("Z2-SEC", "acs", "Z2-SUP", "bms", "events", WRITE)
    assert go("Z4-ENT", "vendor", "Z3-DMZ", "jump-host", "session")
    assert go("Z3-DMZ", "jump-host", "Z2-SUP", "workstation", "session", permit=True)
    assert not go("Z3-DMZ", "jump-host", "Z2-SUP", "workstation", "session")


# --- violations -------------------------------------------------------------------------------


@pytest.mark.req("ADC-NET-003")
def test_each_blocked_attempt_is_a_security_event_at_once() -> None:
    kernel, _, maps, net = facility()
    heard: list[Any] = []
    kernel.events.subscribe("net.violation", heard.append)
    kernel.run_for(7000)
    allowed = net.request(Request("ZA-AGENT", "agent-1", "Z3-DMZ", "gate", "https"))
    assert allowed.allowed and len(net.violations) == 0 and not heard
    net.request(Request("ZA-AGENT", "agent-1", "Z1-CHW", "cooling.chw_plant[CHW]", "bacnet"))
    target = next(m for m in maps if m.tag == CHWS and m.protocol == "bacnet")
    net.request(
        Request("Z2-SUP", "bms", target.zone, target.device, "bacnet", WRITE,
                target.object_type, target.address)
    )  # fmt: skip
    entries = net.violations.entries()
    assert [e["time_ms"] for e in entries] == [7000, 7000], "within 5 simulated seconds"
    first, second = entries
    assert (first["source_zone"], first["destination_zone"]) == ("ZA-AGENT", "Z1-CHW")
    assert first["destination"] == "cooling.chw_plant[CHW]" and "no conduit" in str(first["rule"])
    assert second["conduit"] == "C1" and "command service only" in str(second["rule"])
    assert second["source_host"] == "bms" and second["address"] == target.address
    assert len(heard) == 2 and heard[0].payload["source_zone"] == "ZA-AGENT"


@pytest.mark.req("ADC-NET-003")
def test_the_violation_log_is_append_only_and_part_of_the_state() -> None:
    kernel, _, _, net = facility()
    before = kernel.state_hash()
    net.request(Request("Z4-ENT", "x", "Z2-SUP", "bms", "https"))
    assert kernel.state_hash() != before
    with pytest.raises(LogIntegrityError):
        net.violations.truncate(0, "mallory")
    assert [e["kind"] for e in net.violations.entries()] == ["violation", "integrity_violation"]
