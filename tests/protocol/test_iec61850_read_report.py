"""ADC-IEC-002: an MMS read is the point database sample; trips are reported with relay time."""

from typing import Any

import pytest

SWITCHBOARD = ("electrical.mv_switchgear", "SWG-MV")
TRIP = "electrical.mv_switchgear[SWG-MV].fdr_a_trip"
CLOSED = "electrical.mv_switchgear[SWG-MV].fdr_a_brk_closed"


def connect(site: Any, relay: str) -> Any:
    from agentic_datacenter_iec61850.client import MmsClient

    return MmsClient("127.0.0.1", site.ports[relay])


def served(binding: Any, value: Any) -> Any:
    """Return what a point value is on the wire for *binding*."""
    how = binding.convert
    if how == "float":
        return pytest.approx(float(value), rel=1e-6, abs=1e-6)
    if how == "dbpos":
        return 1 if value else 2  # on, off
    if how == "ms":
        return round(float(value) * 1000)
    if how.startswith("equals:"):
        return value == how.partition(":")[2]
    if how.startswith("differs:"):
        return value != how.partition(":")[2]
    return bool(value)


@pytest.mark.req("ADC-IEC-002")
def test_every_mapped_point_reads_as_the_point_database_holds_it_in_the_same_step(
    relay_site: Any,
) -> None:
    from agentic_datacenter_iec61850.client import old_data, validity

    site, checked = relay_site, 0
    site.kernel.run_for(1000)
    for relay, model in site.view.relays.items():
        with connect(site, relay) as client:
            for binding in model.bindings:
                record = site.points.read(binding.tag)
                value = client.read(model.reference(binding.ref), binding.fc)
                assert value == served(binding, record.value), (relay, binding.ref)
                if binding.fc in ("ST", "MX"):
                    data = site.view.data_object(relay, binding.ref)
                    quality = client.read(model.reference(f"{data}.q"), binding.fc)
                    assert record.quality == "good" and validity(quality) == "good"
                    assert not old_data(quality)
                checked += 1
    assert checked == sum(len(m.bindings) for m in site.view.relays.values()) > 80


@pytest.mark.req("ADC-IEC-002")
def test_a_value_that_changes_in_the_plant_changes_on_the_wire_with_the_relays_time(
    relay_site: Any,
) -> None:
    from agentic_datacenter_iec61850.model import EPOCH_MS

    site = relay_site
    model = site.view.relays["IED-BUS"]
    reference = model.reference("LD0/MMXU1.PhV.phsA")
    tag = "electrical.mv_switchgear[SWG-MV].bus_v_pu"
    utility = [site.plant.module("electrical.utility", name) for name in ("INC-1", "INC-2")]
    with connect(site, "IED-BUS") as client:
        (((volts,),), _, first) = client.read(reference, "MX")
        assert volts == pytest.approx(1.0)
        site.kernel.run_for(700)
        changed_ms = site.kernel.clock.now_ms
        for source in utility:
            # Inside the tolerance of the transfer controllers: nothing else moves.
            source.inject("set", voltage_pu=0.95)
        site.kernel.run_for(2000)
        try:
            (((volts,),), quality, stamp) = client.read(reference, "MX")
            assert volts == pytest.approx(0.95) == site.points.read(tag).value
            assert quality == 0
            # The step in which the value changed at the relay (the switchboard sees
            # its supply one step late), on the relay's simulated clock.
            assert changed_ms <= stamp - EPOCH_MS <= changed_ms + 200 and stamp > first
        finally:
            for source in utility:
                source.inject("restore")
            site.kernel.run_for(1000)
        assert client.read(reference, "MX")[0] == [[pytest.approx(1.0)]]


@pytest.mark.req("ADC-IEC-002")
def test_stale_quality_in_the_point_database_is_stale_quality_on_the_wire(relay_site: Any) -> None:
    from agentic_datacenter_iec61850.client import old_data, validity

    site = relay_site
    model = site.view.relays["IED-FDR-B"]
    with connect(site, "IED-FDR-B") as client:
        site.points.set_link(False)
        try:
            site.kernel.run_for(4000)
            for binding in model.bindings:
                record = site.points.read(binding.tag)
                assert record.quality == "stale"
                assert client.read(model.reference(binding.ref), binding.fc) == served(
                    binding, record.value
                )
            quality = client.read(model.reference("LD0/MMXU1.TotW.q"), "MX")
            assert validity(quality) == "questionable" and old_data(quality)
        finally:
            site.points.set_link(True)
            site.kernel.run_for(1000)
        assert validity(client.read(model.reference("LD0/MMXU1.TotW.q"), "MX")) == "good"


@pytest.mark.req("ADC-IEC-002")
def test_a_trip_and_the_breaker_opening_are_reported_within_a_second_with_the_relays_timestamp(
    relay_site: Any,
) -> None:
    from agentic_datacenter_iec61850.model import EPOCH_MS

    site = relay_site
    switchboard = site.plant.module(*SWITCHBOARD)
    trips: list[Any] = []
    site.kernel.events.subscribe("protection.trip", trips.append)
    domain = site.view.relays["IED-FDR-A"].domain
    buffered, unbuffered = f"{domain}/LLN0.BR.brcbEvents01", f"{domain}/LLN0.RP.urcbEvents01"
    with connect(site, "IED-FDR-A") as client, connect(site, "IED-FDR-B") as other:
        assert client.subscribe(buffered) == "ok" and client.subscribe(unbuffered) == "ok"
        assert other.subscribe("IED_FDR_BLD0/LLN0.RP.urcbEvents01") == "ok"
        while client.next_report(0.3) is not None:
            pass  # what a buffered block had kept from before this client
        # Five times pickup: 0.43 s on the standard inverse curve at TMS 0.1.
        switchboard.inject("fault_current", node="feeder[A]", amps=300.0)
        received: list[tuple[int, Any]] = []
        try:
            for _ in range(15):
                site.kernel.run_for(100)
                report = client.next_report(1.0 if not received else 0.3)
                while report is not None:
                    received.append((site.kernel.clock.now_ms, report))
                    report = client.next_report(0.3)
            assert len(trips) == 1 and trips[0].payload["relay"] == "IED-FDR-A"
            tripped_ms = trips[0].time_ms
            assert site.points.read(TRIP).value == "PTOC"
            assert site.points.read(CLOSED).value is False

            for block in (buffered, unbuffered):
                mine = [(at, r) for at, r in received if r.control_block == block]
                at, report = next(x for x in mine if x[1].value("LD0/PTRC1.Tr[ST]") is not None)
                general, quality, stamp = report.value("LD0/PTRC1.Tr[ST]")
                assert general is True and quality == 0
                assert stamp == EPOCH_MS + tripped_ms, "the relay's own time of the trip"
                assert 0 < at - tripped_ms <= 1000, "reported within one simulated second"
                assert report.value("LD0/PTOC1.Op[ST]")[0] is True
                assert report.value("LD0/PIOC1.Op[ST]") is None, "only what changed is included"
                assert {why for _, why, _ in report.entries} == {"data-change"}

                at, report = next(x for x in mine if x[1].value("LD0/XCBR1.Pos[ST]") is not None)
                position, _, stamp = report.value("LD0/XCBR1.Pos[ST]")
                assert position == 2, "off: the breaker opened"
                # Breaker operating time 50 ms: open at the first step boundary after it.
                assert tripped_ms < stamp - EPOCH_MS <= tripped_ms + 300
                assert 0 < at - (stamp - EPOCH_MS) <= 1000
            assert other.next_report(0.3) is None, "feeder B's relay has nothing to report"
        finally:
            switchboard.inject("clear_fault", node="feeder[A]")
            switchboard.inject("reset", breaker="feeder[A]")
            site.kernel.run_for(1000)
        # The reset is reported too, and a read agrees with the report.
        closing = [client.next_report(1.0) for _ in range(4)]
        assert any(r is not None and r.value("LD0/XCBR1.Pos[ST]") for r in closing)
        assert client.read(f"{domain}/XCBR1.Pos.stVal", "ST") == 1
