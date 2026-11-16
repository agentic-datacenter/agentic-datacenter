"""ADC-IEC-003: control, setting-group change, configuration write and file services.

Each is refused by the relay and dropped by the conduit into ``Z1-MV``, and
each refusal is a violation event. The conduit half needs no protocol library
and runs everywhere; the relay half runs where the library is installed
(ADR 0017).
"""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.net.maps import protocol_maps
from agentic_datacenter.net.virtual_net import Request, build_network
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[2]
RELAYS = ("IED-BUS", "IED-FDR-A", "IED-FDR-B", "IED-FDR-C", "IED-INC-1", "IED-INC-2")
DENIED = ("control", "setting-group", "write", "file")
SWITCHBOARD = "electrical.mv_switchgear[SWG-MV]"

# --- the conduit ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def conduit() -> Any:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    events: list[Any] = []
    kernel.events.subscribe("net.violation", events.append)
    return build_network(kernel, plant, points), protocol_maps(points), events


def mms(relay: str, operation: str, host: str = "pms", zone: str = "Z2-SUP") -> Request:
    return Request(zone, host, "Z1-MV", relay, "mms", operation)


@pytest.mark.req("ADC-IEC-003")
def test_the_relays_are_the_mms_devices_of_the_conduit_allowlist(conduit: Any) -> None:
    _, maps, _ = conduit
    relay_maps = [m for m in maps if m.protocol == "mms"]
    assert {m.device for m in relay_maps} == set(RELAYS)
    assert {m.zone for m in relay_maps} == {"Z1-MV"}
    assert not any(m.writable for m in relay_maps), "nothing in a relay is writable (SDD 8.2)"
    assert {m.device for m in relay_maps if "fdr_a_" in m.tag} == {"IED-FDR-A"}
    assert {m.device for m in relay_maps if ".bus_" in m.tag} == {"IED-BUS"}


@pytest.mark.req("ADC-IEC-003")
@pytest.mark.parametrize("relay", RELAYS)
def test_read_and_report_pass_the_conduit_from_a_supervisory_reader(
    conduit: Any, relay: str
) -> None:
    network, _, events = conduit
    before = len(events)
    for operation in ("connect", "read", "report"):
        answer = network.request(mms(relay, operation))
        assert answer.allowed and answer.conduit == "C1", operation
    assert len(events) == before


@pytest.mark.req("ADC-IEC-003")
@pytest.mark.parametrize("operation", DENIED)
@pytest.mark.parametrize("relay", RELAYS)
def test_the_conduit_drops_every_other_service_class_with_a_violation_event(
    conduit: Any, relay: str, operation: str
) -> None:
    network, _, events = conduit
    logged = len(network.violations)
    for host in ("pms", "command-service"):
        answer = network.request(mms(relay, operation, host))
        assert not answer.allowed and answer.conduit == "C1"
        assert "read and report only" in answer.rule
        event = events[-1].payload
        assert (event["source_zone"], event["source_host"]) == ("Z2-SUP", host)
        assert (event["destination"], event["operation"]) == (relay, operation)
        assert event["protocol"] == "mms" and event["rule"] == answer.rule
    assert len(network.violations) == logged + 2


@pytest.mark.req("ADC-IEC-003")
def test_the_conduit_allowlists_by_client_and_by_relay(conduit: Any) -> None:
    network, _, _ = conduit
    stranger = network.request(mms("IED-FDR-A", "read", host="workstation-7"))
    assert not stranger.allowed and "not on the allowlist" in stranger.rule
    unknown = network.request(mms("IED-FDR-Z", "read"))
    assert not unknown.allowed and "no mms device" in unknown.rule
    for zone, host in (("ZA-AGENT", "agent-1"), ("Z4-ENT", "laptop"), ("Z3-DMZ", "gate")):
        for operation in ("connect", "read", "control"):
            answer = network.request(mms("IED-FDR-A", operation, host, zone))
            assert not answer.allowed and answer.conduit == "", (zone, operation)


# --- the relay -----------------------------------------------------------------------------


def connect(site: Any, relay: str = "IED-FDR-A") -> Any:
    from agentic_datacenter_iec61850.client import MmsClient

    return MmsClient("127.0.0.1", site.ports[relay])


def state(site: Any) -> dict[str, Any]:
    """Breaker positions, trips and settings: everything a request could have changed."""
    return {
        tag: site.points.read(tag).value
        for tag in site.points.tags()
        if tag.startswith(SWITCHBOARD) and site.points.read(tag).kind != "analog_in"
    }


ATTEMPTS = {
    "operate the breaker": ("control", lambda c, d: c.operate(f"{d}/XCBR1.Pos", False)),
    "operate through the switch controller": (
        "control", lambda c, d: c.operate(f"{d}/CSWI1.Pos", False)),
    "change the active setting group": (
        "setting-group", lambda c, d: c.set_active_setting_group(d, 2)),
    "open a setting group for editing": ("setting-group", lambda c, d: c.edit_setting_group(d, 1)),
    "write a protection setting": (
        "configuration-write", lambda c, d: c.write(f"{d}/PTOC1.StrVal.setMag.f", "SP", 5000.0)),
    "write the time multiplier": (
        "configuration-write", lambda c, d: c.write(f"{d}/PTOC1.TmMult.setMag.f", "SP", 1.5)),
    "write a control model": (
        "configuration-write", lambda c, d: c.write(f"{d}/XCBR1.Pos.ctlModel", "CF", 1)),
    "write a description": (
        "configuration-write", lambda c, d: c.write(f"{d}/LLN0.NamPlt.d", "DC", "mine")),
    "create a data set": (
        "configuration-write",
        lambda c, d: c.create_data_set(f"{d}/LLN0.mine", (f"{d}/XCBR1.Pos[ST]",))),
    "list the files": ("file", lambda c, d: c.file_directory()),
    "fetch a file": ("file", lambda c, d: c.get_file("settings.cfg")),
    "delete a file": ("file", lambda c, d: c.delete_file("settings.cfg")),
}  # fmt: skip


@pytest.mark.req("ADC-IEC-003")
@pytest.mark.parametrize("attempt", sorted(ATTEMPTS))
def test_the_relay_refuses_with_an_access_error_and_a_violation_event(
    relay_site: Any, attempt: str
) -> None:
    site = relay_site
    service, call = ATTEMPTS[attempt]
    published: list[Any] = []
    site.kernel.events.subscribe("net.device_violation", published.append)
    before, recorded = state(site), len(site.view.violations())
    seen = len(published)
    with connect(site) as client:
        domain = client.directory().domain
        assert call(client, domain) == "access-denied"
        assert client.read(f"{domain}/XCBR1.Pos.stVal", "ST") == 1, "still closed"
        assert client.read(f"{domain}/LLN0.SGCB.ActSG", "SP") == 1
        assert client.read(f"{domain}/PTOC1.StrVal.setMag.f", "SP") == pytest.approx(60.0)
        assert client.read(f"{domain}/XCBR1.Pos.ctlModel", "CF") == 0
    violations = site.view.violations()[recorded:]
    assert len(violations) == 1, violations
    violation = violations[0]
    assert violation["device"] == "IED-FDR-A" and violation["service"] == service
    assert violation["protocol"] == "mms"
    assert str(violation["client"]).startswith("127.0.0.1:"), "the address the request came from"
    assert violation["time_ms"] == site.kernel.clock.now_ms
    assert [dict(e.payload) for e in published[seen:]] == [violation]
    assert state(site) == before, "breaker and settings unchanged"


@pytest.mark.req("ADC-IEC-003")
def test_select_and_writes_to_live_data_are_refused_too(relay_site: Any) -> None:
    """Refused by the library itself, which does not tell the server (ADR 0017)."""
    site = relay_site
    before = state(site)
    with connect(site) as client:
        domain = client.directory().domain
        assert client.select(f"{domain}/XCBR1.Pos", False) == "object-does-not-exist"
        assert client.write(f"{domain}/MMXU1.TotW.mag.f", "MX", 0.0) == "access-denied"
        assert client.write(f"{domain}/PTRC1.Tr.general", "ST", True) == "access-denied"
    site.kernel.run_for(1000)
    assert state(site) == before


@pytest.mark.req("ADC-IEC-003")
def test_every_relay_refuses_not_only_the_feeder(relay_site: Any) -> None:
    site = relay_site
    for relay in RELAYS:
        recorded = len(site.view.violations())
        with connect(site, relay) as client:
            domain = client.directory().domain
            assert client.set_active_setting_group(domain, 2) == "access-denied"
            assert client.file_directory() == "access-denied"
            if relay != "IED-BUS":
                assert client.operate(f"{domain}/XCBR1.Pos", False) == "access-denied"
        fresh = site.view.violations()[recorded:]
        assert {v["device"] for v in fresh} == {relay}
        assert len(fresh) == (2 if relay == "IED-BUS" else 3)


@pytest.mark.req("ADC-IEC-003")
def test_reading_and_subscribing_raise_no_violation(relay_site: Any) -> None:
    site = relay_site
    recorded = len(site.view.violations())
    with connect(site) as client:
        domain = client.directory().domain
        client.read(f"{domain}/MMXU1.TotW", "MX")
        assert client.subscribe(f"{domain}/LLN0.RP.urcbMeas01", general_interrogation=True) == "ok"
        assert client.next_report(5.0) is not None
    assert len(site.view.violations()) == recorded


@pytest.mark.req("ADC-SAF-001")
def test_a_relay_binds_to_loopback_unless_told_otherwise(relay_site: Any) -> None:
    from agentic_datacenter_iec61850.guard import ExternalAddressError
    from agentic_datacenter_iec61850.server import Iec61850Server

    server = Iec61850Server(relay_site.view, "IED-BUS")
    for host in ("0.0.0.0", "192.168.1.10", "relay.example.com"):
        with pytest.raises(ExternalAddressError):
            server.start(host, 0)
