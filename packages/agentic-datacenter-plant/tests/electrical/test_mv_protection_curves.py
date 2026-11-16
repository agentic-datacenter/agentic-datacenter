"""ADC-IEC-004: protection elements of the 36 kV switchboard."""

from typing import Any

import pytest

from agentic_datacenter.core.ports import ElectricalDemand, ElectricalSupply
from agentic_datacenter.plant.electrical.mv_switchgear import MODULE
from agentic_datacenter.plant.electrical.mv_switchgear.model import standard_inverse_s

LIVE = ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0)
DEAD = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)
TRAINS = ("A", "B", "C")
PICKUP_A, TMS, INSTANT_A = 60.0, 0.1, 600.0


def switchboard(rig: Any, load_kw: float = 1000.0) -> Any:
    r = rig(MODULE, keys={"trains": TRAINS})
    r.forward = {"incomer_1": LIVE, "incomer_2": LIVE}
    r.reverse = {f"feeder[{k}]": ElectricalDemand(load_kw) for k in TRAINS}
    r.run(1)
    return r


def test_standard_inverse_characteristic_matches_the_closed_form() -> None:
    assert standard_inverse_s(2.0, 1.0) == pytest.approx(0.14 / (2.0**0.02 - 1.0))
    assert standard_inverse_s(10.0, 0.1) == pytest.approx(0.297, abs=0.001)
    assert standard_inverse_s(1.0, 1.0) == float("inf")
    assert standard_inverse_s(0.5, 1.0) == float("inf")


def test_feeders_are_live_and_demand_is_shared_by_the_two_incomers(rig: Any) -> None:
    r = switchboard(rig)
    assert all(r.out(f"feeder[{k}]") == LIVE for k in TRAINS)
    assert r.back("incomer_1") == r.back("incomer_2") == ElectricalDemand(1500.0)


def test_loss_of_one_incomer_moves_all_demand_to_the_other(rig: Any) -> None:
    r = switchboard(rig)
    r.forward["incomer_1"] = DEAD
    r.run(1)
    assert r.out("feeder[A]") == LIVE
    assert r.back("incomer_1") == ElectricalDemand(0.0)
    assert r.back("incomer_2") == ElectricalDemand(3000.0)
    r.forward["incomer_2"] = DEAD
    r.run(1)
    assert all(not r.out(f"feeder[{k}]").energized for k in TRAINS)


def test_load_current_alone_never_trips(rig: Any) -> None:
    r = switchboard(rig, load_kw=2300.0)  # close to transformer rating, about 39 A
    r.run(600)
    assert r.module.io["fdr_a_current_a"] == pytest.approx(
        2300.0 / (3**0.5 * 36.0 * 0.95), rel=1e-6
    )
    assert r.module.io["fdr_a_brk_closed"] is True and r.module.io["fdr_a_trip"] == "NONE"


@pytest.mark.req("ADC-IEC-004")
@pytest.mark.parametrize("multiple", [1.5, 2.0, 3.0, 5.0, 10.0, 20.0])
def test_inverse_time_trip_matches_the_characteristic_within_five_percent(
    rig: Any, multiple: float
) -> None:
    r = switchboard(rig, load_kw=0.0)
    # Stay under the instantaneous pickup so the inverse-time element is the one that operates.
    r.module.io["fdr_a_inst_a"] = 5000.0
    r.module.inject("fault_current", node="feeder[A]", amps=multiple * PICKUP_A)
    r.until(lambda: r.module.io["fdr_a_trip"] != "NONE", limit_s=120)
    expected = TMS * 0.14 / (multiple**0.02 - 1.0)
    assert r.module.io["fdr_a_trip"] == "PTOC"
    assert r.module.io["fdr_a_operate_s"] == pytest.approx(expected, rel=0.05)


@pytest.mark.req("ADC-IEC-004")
def test_breaker_opens_one_operating_time_after_the_relay_operates(rig: Any) -> None:
    r = switchboard(rig, load_kw=0.0)
    r.module.io["fdr_a_inst_a"] = 5000.0
    start = r.now_s
    r.module.inject("fault_current", node="feeder[A]", amps=10 * PICKUP_A)
    r.until(lambda: not r.out("feeder[A]").energized, limit_s=10)
    operate = TMS * 0.14 / (10**0.02 - 1.0)
    assert operate + 0.05 <= r.now_s - start <= operate + 0.05 + 0.2
    assert r.out("feeder[B]") == LIVE, "only the faulted feeder is cleared"


@pytest.mark.req("ADC-IEC-004")
@pytest.mark.parametrize("amps", [INSTANT_A, 2 * INSTANT_A, 20 * INSTANT_A])
def test_instantaneous_trip_is_within_one_control_step_plus_breaker_time(
    rig: Any, amps: float
) -> None:
    r = switchboard(rig, load_kw=0.0)
    r.module.inject("fault_current", node="feeder[A]", amps=amps)
    r.step()
    assert r.module.io["fdr_a_trip"] == "PIOC", "the relay operates in the step it sees the current"
    assert r.module.io["fdr_a_operate_s"] <= 0.1
    r.step()
    assert not r.out("feeder[A]").energized, "the breaker has opened one operating time later"
    assert r.module.io["fdr_a_brk_closed"] is False


@pytest.mark.req("ADC-IEC-004")
def test_current_below_pickup_never_operates_and_a_cleared_fault_resets_the_element(
    rig: Any,
) -> None:
    r = switchboard(rig, load_kw=0.0)
    r.module.io["fdr_a_inst_a"] = 5000.0
    r.module.inject("fault_current", node="feeder[A]", amps=0.99 * PICKUP_A)
    r.run(300)
    assert r.module.io["fdr_a_trip"] == "NONE"
    r.module.inject("fault_current", node="feeder[A]", amps=2 * PICKUP_A)
    r.run(0.5 * TMS * 0.14 / (2**0.02 - 1.0))
    r.module.inject("clear_fault", node="feeder[A]")
    r.run(60)
    assert r.module.io["fdr_a_trip"] == "NONE" and r.module.io["fdr_a_brk_closed"] is True


@pytest.mark.req("ADC-IEC-004")
def test_feeder_relay_clears_its_fault_before_the_incomer_relays_operate(rig: Any) -> None:
    r = switchboard(rig, load_kw=500.0)
    r.module.io["fdr_b_inst_a"] = 5000.0
    r.module.inject("fault_current", node="feeder[B]", amps=400.0)
    r.run(30)
    assert r.module.io["fdr_b_trip"] == "PTOC"
    assert r.module.io["inc_1_trip"] == "NONE" and r.module.io["inc_2_trip"] == "NONE"
    assert r.out("feeder[A]") == LIVE and r.out("feeder[C]") == LIVE


def test_tripped_feeder_stays_open_until_reset_at_the_relay(rig: Any) -> None:
    r = switchboard(rig, load_kw=0.0)
    r.module.inject("fault_current", node="feeder[A]", amps=INSTANT_A)
    r.run(1)
    r.module.inject("clear_fault", node="feeder[A]")
    r.run(60)
    assert not r.out("feeder[A]").energized
    r.module.inject("reset", breaker="feeder[A]")
    r.run(1)
    assert r.out("feeder[A]") == LIVE and r.module.io["fdr_a_trip"] == "NONE"


def test_feeder_can_be_opened_and_closed_locally(rig: Any) -> None:
    r = switchboard(rig)
    r.module.inject("manual_open", breaker="feeder[C]")
    r.run(1)
    assert not r.out("feeder[C]").energized and r.out("feeder[A]") == LIVE
    r.module.inject("manual_close", breaker="feeder[C]")
    r.run(1)
    assert r.out("feeder[C]") == LIVE


def test_bus_voltage_elements_report_with_a_definite_time_delay(rig: Any) -> None:
    r = switchboard(rig)
    sag = ElectricalSupply(True, 0.8, 1.0)
    r.forward = {"incomer_1": sag, "incomer_2": sag}
    r.run(1.5)
    assert r.module.io["bus_undervoltage"] is False, "definite time has not elapsed"
    r.run(1)
    assert r.module.io["bus_undervoltage"] is True
    assert all(r.module.io[f"fdr_{k.lower()}_brk_closed"] for k in TRAINS), (
        "the bus relay trips nothing"
    )
    r.forward = {"incomer_1": LIVE, "incomer_2": LIVE}
    r.run(1)
    assert r.module.io["bus_undervoltage"] is False


@pytest.mark.req("ADC-PRC-001")
def test_power_into_the_switchboard_equals_power_out_at_every_step(rig: Any) -> None:
    r = switchboard(rig, load_kw=900.0)
    r.module.inject("fault_current", node="feeder[A]", amps=INSTANT_A)
    for _ in range(50):
        r.step()
        b = r.module.power_balance()
        assert b["in_kw"] == pytest.approx(b["out_kw"])
    assert b["out_kw"] == pytest.approx(1800.0)
