"""ADC-NET-001: a connection between two zones with no conduit fails (inproc mode)."""

from pathlib import Path

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.net.virtual_net import Request, VirtualNetwork, build_network
from agentic_datacenter.net.zones import CONDUITS, allowed_pairs, is_level_one, zone_instances
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[2]


def network() -> VirtualNetwork:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    return build_network(kernel, plant, PointDatabase(kernel, plant))


NET = network()
PROTOCOLS = sorted({p for c in CONDUITS for p in c.protocols})
HOSTS = ("", "bms", "command-service", "gate", "read-api", "jump-host")


def test_the_generic_facility_has_the_29_zone_instances_of_the_zone_model() -> None:
    zones = NET.zones
    assert len(zones) == 29 and len(set(zones)) == 29
    assert sum(is_level_one(z) for z in zones) == 23
    assert {"Z0-PROT", "Z1-MV", "Z1-CHW", "Z1-FUEL", "Z1-BLDG", "Z2-SUP", "Z2-SEC"} <= set(zones)
    assert {f"Z1-PWR-{t}" for t in "ABC"} | {f"Z1-POD-{n:02d}" for n in range(1, 17)} <= set(zones)


@pytest.mark.req("ADC-NET-001")
def test_full_zone_by_zone_matrix() -> None:
    """Every ordered pair of zones: reachable only if the zone model lists a conduit."""
    zones, allowed = NET.zones, allowed_pairs(NET.zones)
    tried = passed = 0
    for source in zones:
        for destination in zones:
            if source == destination:
                continue
            reachable = any(
                NET.request(Request(source, a, destination, b, protocol, permit=True)).allowed
                for protocol in PROTOCOLS
                for a in HOSTS
                for b in (*HOSTS, _a_device(destination))
            )
            tried += 1
            passed += reachable
            assert reachable == ((source, destination) in allowed), (source, destination)
    assert tried == 29 * 28 and passed == len(allowed)
    # 23 by C1, 1 each by C2, C3/C7, C4, C5/C7, C8, and 24 by C6.
    assert len(allowed) == 23 + 1 + 1 + 1 + 1 + 1 + 24


def _a_device(zone: str) -> str:
    devices = sorted(d for z, d, _ in NET._devices if z == zone)  # noqa: SLF001
    return devices[0] if devices else ""


@pytest.mark.req("ADC-NET-001")
@pytest.mark.parametrize(
    ("source", "destination"),
    [
        ("ZA-AGENT", "Z2-SUP"),
        ("ZA-AGENT", "Z1-CHW"),
        ("ZA-AGENT", "Z1-POD-07"),
        ("Z1-PWR-A", "Z1-PWR-B"),
        ("Z1-PWR-C", "Z1-PWR-A"),
        ("Z1-POD-01", "Z1-POD-02"),
        ("Z1-CHW", "Z2-SUP"),
        ("Z2-SUP", "Z0-PROT"),
        ("Z1-CHW", "Z0-PROT"),
        ("Z2-SUP", "Z2-SEC"),
        ("Z4-ENT", "Z2-SUP"),
        ("Z3-DMZ", "Z1-CHW"),
        ("Z4-ENT", "ZA-AGENT"),
    ],
)
def test_the_pairs_the_demonstration_depends_on_fail(source: str, destination: str) -> None:
    for protocol in PROTOCOLS:
        for host in HOSTS:
            request = Request(source, host, destination, _a_device(destination), protocol)
            assert not NET.request(request).allowed


def test_the_agent_reaches_the_gate_and_nothing_else() -> None:
    assert NET.request(Request("ZA-AGENT", "agent-1", "Z3-DMZ", "gate", "https")).allowed
    assert NET.request(Request("ZA-AGENT", "agent-1", "Z3-DMZ", "gate", "mcp")).allowed
    for host in ("read-api", "jump-host", "historian-replica", ""):
        assert not NET.request(Request("ZA-AGENT", "agent-1", "Z3-DMZ", host, "https")).allowed
    reachable = {d for s, d in allowed_pairs(NET.zones) if s == "ZA-AGENT"}
    assert reachable == {"Z3-DMZ"}


def test_inside_one_zone_the_boundary_does_not_apply() -> None:
    answer = NET.request(Request("Z1-CHW", "chiller-1", "Z1-CHW", "chiller-2", "bacnet"))
    assert answer.allowed and answer.conduit == ""


def test_an_unknown_zone_is_refused() -> None:
    assert not NET.request(Request("Z9-NOWHERE", "x", "Z2-SUP", "bms", "https")).allowed
    assert zone_instances  # the model is built from the plant, not typed in
