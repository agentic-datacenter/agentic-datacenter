"""Utility, generator, UPS and IT load at fidelity F1."""

from typing import Any

import pytest

from agentic_datacenter.core.ports import (
    AirHeat,
    AirInlet,
    ElectricalDemand,
    ElectricalSupply,
    FuelDemand,
    FuelSupply,
    Signal,
)
from agentic_datacenter.plant.electrical.genset import MODULE as GENSET
from agentic_datacenter.plant.electrical.it_load import MODULE as IT_LOAD
from agentic_datacenter.plant.electrical.ups import MODULE as UPS
from agentic_datacenter.plant.electrical.utility import MODULE as UTILITY

LIVE = ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0)
DEAD = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)


# --- utility ------------------------------------------------------------------


def test_utility_is_nominal_until_the_scenario_disturbs_it(rig: Any) -> None:
    r = rig(UTILITY)
    r.reverse = {"supply": ElectricalDemand(0.0)}
    r.run(1)
    assert r.out("supply") == LIVE
    r.module.inject("set", voltage_pu=0.8, frequency_pu=0.98)
    r.run(1)
    assert r.out("supply") == ElectricalSupply(True, 0.8, 0.98)
    r.module.inject("loss")
    r.run(1)
    assert r.out("supply") == DEAD
    r.module.inject("restore")
    r.run(1)
    assert r.out("supply") == LIVE


# --- generator ----------------------------------------------------------------


def genset(rig: Any, **params: Any) -> Any:
    r = rig(GENSET, params)
    r.forward = {"start_request": Signal(False), "fuel": FuelSupply(True)}
    r.reverse = {"output": ElectricalDemand(0.0), "ready_to_load": None, "fault": None}
    return r


def test_generator_is_ready_to_load_ten_seconds_after_the_start_request(rig: Any) -> None:
    r = genset(rig)
    r.run(2)
    assert r.module.io["state"] == "STOPPED" and not r.out("output").energized
    r.forward["start_request"] = Signal(True)
    took = r.until(lambda: r.out("ready_to_load").active, limit_s=60)
    assert 10.0 <= took <= 10.2
    assert r.out("output").energized
    assert r.module.io["state"] == "READY_TO_LOAD"


def test_generator_stops_when_the_request_is_withdrawn(rig: Any) -> None:
    r = genset(rig)
    r.forward["start_request"] = Signal(True)
    r.run(15)
    r.forward["start_request"] = Signal(False)
    r.run(1)
    assert r.module.io["state"] == "STOPPED"
    assert not r.out("output").energized and not r.out("ready_to_load").active


def test_generator_that_fails_to_start_raises_its_fault_signal(rig: Any) -> None:
    r = genset(rig)
    r.module.inject("start_failure")
    r.forward["start_request"] = Signal(True)
    r.run(30)
    assert r.module.io["state"] == "FAULT"
    assert r.out("fault").active and not r.out("ready_to_load").active
    r.module.inject("reset")
    r.run(15)
    assert r.out("ready_to_load").active, "the next start succeeds"


def test_generator_without_fuel_faults(rig: Any) -> None:
    r = genset(rig)
    r.forward["start_request"] = Signal(True)
    r.run(15)
    r.forward["fuel"] = FuelSupply(False)
    r.run(1)
    assert r.module.io["state"] == "FAULT" and not r.out("output").energized


def test_fuel_burn_is_linear_between_quarter_and_full_load(rig: Any) -> None:
    r = genset(rig, rated_kw=1800.0, fuel_l_per_h_full=430.0, fuel_l_per_h_quarter=130.0)
    r.forward["start_request"] = Signal(True)
    r.run(15)
    burn = {}
    for fraction in (0.25, 0.625, 1.0):
        r.reverse["output"] = ElectricalDemand(1800.0 * fraction)
        r.run(20)
        burn[fraction] = r.back("fuel").litre_per_h
    assert burn[0.25] == pytest.approx(130.0) and burn[1.0] == pytest.approx(430.0)
    assert burn[0.625] == pytest.approx((130.0 + 430.0) / 2)
    r.forward["start_request"] = Signal(False)
    r.run(1)
    assert r.back("fuel") == FuelDemand(0.0)


def test_load_step_within_the_class_stays_inside_the_g3_limits_and_recovers(rig: Any) -> None:
    r = genset(rig)
    r.forward["start_request"] = Signal(True)
    r.run(15)
    r.reverse["output"] = ElectricalDemand(0.6 * 1800.0)
    lowest_f, lowest_v = 1.0, 1.0
    for _ in range(30):
        r.step()
        lowest_f = min(lowest_f, r.out("output").frequency_pu)
        lowest_v = min(lowest_v, r.out("output").voltage_pu)
    assert 0.93 - 1e-9 <= lowest_f < 0.95, "G3: frequency dip at most 7 %"
    assert 0.85 - 1e-9 <= lowest_v < 0.90, "G3: voltage dip at most 15 %"
    assert abs(r.out("output").frequency_pu - 1.0) <= 0.005, "recovered within 3 s"
    r.run(1)
    assert abs(r.out("output").voltage_pu - 1.0) <= 0.01, "recovered within 4 s"


def test_load_step_beyond_the_class_shows_a_larger_excursion(rig: Any) -> None:
    r = genset(rig)
    r.forward["start_request"] = Signal(True)
    r.run(15)
    r.reverse["output"] = ElectricalDemand(1800.0)
    r.step()
    r.step()
    assert r.out("output").frequency_pu < 0.93


def test_load_rejection_raises_frequency_within_the_g3_limit(rig: Any) -> None:
    r = genset(rig)
    r.forward["start_request"] = Signal(True)
    r.reverse["output"] = ElectricalDemand(0.6 * 1800.0)
    r.run(30)
    r.reverse["output"] = ElectricalDemand(0.0)
    highest = max((r.step(), r.out("output").frequency_pu)[1] for _ in range(20))
    assert 1.05 < highest <= 1.10 + 1e-9


def test_sustained_overload_trips_the_generator(rig: Any) -> None:
    r = genset(rig)
    r.forward["start_request"] = Signal(True)
    r.run(15)
    r.reverse["output"] = ElectricalDemand(1.2 * 1800.0)
    r.run(5)
    assert r.module.io["state"] == "LOADED"
    r.run(10)
    assert r.module.io["state"] == "FAULT"


# --- UPS ----------------------------------------------------------------------


def ups(rig: Any, load_kw: float, **params: Any) -> Any:
    r = rig(UPS, params)
    r.forward = {"input": LIVE}
    r.reverse = {"output": ElectricalDemand(load_kw), "heat": AirInlet(22.0)}
    return r


def test_ups_online_feeds_the_load_and_draws_its_losses(rig: Any) -> None:
    r = ups(rig, 1200.0)
    r.run(2)
    assert r.out("output") == LIVE and r.module.io["mode"] == "ONLINE"
    assert r.back("input").kw == pytest.approx(1200.0 / 0.96)
    assert r.out("heat").heat_kw == pytest.approx(1200.0 / 0.96 - 1200.0)


@pytest.mark.req("ADC-PRC-003")
@pytest.mark.parametrize("autonomy_s", [300.0, 600.0])
def test_ups_autonomy_at_full_load_equals_the_profile_value(rig: Any, autonomy_s: float) -> None:
    r = ups(rig, 1200.0, autonomy_s=autonomy_s)
    r.run(2)
    r.forward["input"] = DEAD
    lasted = r.until(lambda: not r.out("output").energized, limit_s=2 * autonomy_s)
    assert lasted == pytest.approx(autonomy_s, rel=0.05)
    assert r.module.io["mode"] == "DEPLETED" and r.module.io["soc_pct"] == 0.0


@pytest.mark.req("ADC-PRC-003")
def test_ups_at_half_load_lasts_twice_as_long(rig: Any) -> None:
    r = ups(rig, 600.0)
    r.run(2)
    r.forward["input"] = DEAD
    lasted = r.until(lambda: not r.out("output").energized, limit_s=1000)
    assert lasted == pytest.approx(600.0, rel=0.05)


def test_ups_bridges_a_short_outage_and_recharges_at_a_limited_rate(rig: Any) -> None:
    r = ups(rig, 1200.0)
    r.run(2)
    r.forward["input"] = DEAD
    r.run(20)
    assert r.out("output") == LIVE and r.module.io["mode"] == "ON_BATTERY"
    assert r.back("input") == ElectricalDemand(0.0)
    soc = r.module.io["soc_pct"]
    assert soc == pytest.approx(100.0 * (1 - 20 / 300), abs=0.5)
    r.forward["input"] = LIVE
    r.run(2)
    assert r.module.io["mode"] == "ONLINE"
    assert r.back("input").kw == pytest.approx(1200.0 / 0.96 + 120.0), (
        "recharge limit 10 % of rating"
    )
    r.until(lambda: r.module.io["soc_pct"] == 100.0, limit_s=600)
    r.run(1)
    assert r.back("input").kw == pytest.approx(1200.0 / 0.96)


def test_ups_goes_to_battery_when_its_input_leaves_the_tolerance_band(rig: Any) -> None:
    r = ups(rig, 600.0)
    r.run(2)
    r.forward["input"] = ElectricalSupply(True, 0.85, 1.0)
    r.run(1)
    assert r.module.io["mode"] == "ON_BATTERY" and r.out("output") == LIVE
    r.forward["input"] = ElectricalSupply(True, 0.93, 1.0)
    r.run(1)
    assert r.module.io["mode"] == "ONLINE"


def test_ups_fault_transfers_the_load_to_static_bypass(rig: Any) -> None:
    r = ups(rig, 600.0)
    r.run(2)
    r.module.inject("fault")
    r.forward["input"] = ElectricalSupply(True, 0.97, 1.0)
    r.run(1)
    assert r.module.io["mode"] == "BYPASS"
    assert r.out("output") == ElectricalSupply(True, 0.97, 1.0), "the load sees the source"
    assert r.back("input") == ElectricalDemand(600.0)
    r.forward["input"] = DEAD
    r.run(1)
    assert not r.out("output").energized, "no ride-through on bypass"


@pytest.mark.req("ADC-PRC-001")
def test_ups_power_balances_at_every_step_through_an_outage_and_recharge(rig: Any) -> None:
    r = ups(rig, 900.0)
    for phase, feed, steps in (
        ("online", LIVE, 30),
        ("battery", DEAD, 300),
        ("recharge", LIVE, 600),
    ):
        r.forward["input"] = feed
        for _ in range(steps):
            r.step()
            b = r.module.power_balance()
            residual = b["in_kw"] - b["out_kw"] - b["loss_kw"] - b["stored_kw"]
            assert abs(residual) <= 1e-3 * max(b["in_kw"], b["out_kw"], 1.0), phase


# --- IT load -------------------------------------------------------------------


def it_load(rig: Any) -> Any:
    r = rig(IT_LOAD, {"design_kw": 150.0})
    r.forward = {"feed_a": LIVE, "feed_b": LIVE, "epo": Signal(False)}
    r.reverse = {"heat": AirInlet(22.0)}
    return r


def test_it_load_splits_over_two_feeds_and_moves_to_one_when_the_other_dies(rig: Any) -> None:
    r = it_load(rig)
    r.run(1)
    assert r.back("feed_a") == r.back("feed_b") == ElectricalDemand(75.0)
    assert r.out("heat") == AirHeat(heat_kw=150.0, airflow_kg_s=12.0)
    r.forward["feed_a"] = DEAD
    r.run(1)
    assert r.back("feed_a") == ElectricalDemand(0.0) and r.back("feed_b") == ElectricalDemand(150.0)
    assert r.module.io["kwh_lost"] == 0.0


def test_it_load_counts_the_energy_it_could_not_draw(rig: Any) -> None:
    r = it_load(rig)
    r.run(1)
    r.forward["feed_a"] = r.forward["feed_b"] = DEAD
    r.run(60)
    assert r.module.io["served_kw"] == 0.0 and r.module.io["dropped"] is True
    assert r.module.io["kwh_lost"] == pytest.approx(150.0 * 60 / 3600, rel=0.01)
    r.forward["feed_b"] = LIVE
    r.run(1)
    assert r.module.io["served_kw"] == 150.0 and r.module.io["dropped"] is False


def test_it_load_does_not_run_on_a_feed_outside_its_input_range(rig: Any) -> None:
    r = it_load(rig)
    r.forward["feed_a"] = ElectricalSupply(True, 0.85, 1.0)
    r.run(1)
    assert r.back("feed_a") == ElectricalDemand(0.0) and r.back("feed_b") == ElectricalDemand(150.0)


def test_emergency_power_off_removes_the_load(rig: Any) -> None:
    r = it_load(rig)
    r.forward["epo"] = Signal(True)
    r.run(1)
    assert r.module.io["served_kw"] == 0.0 and r.out("heat").heat_kw == 0.0
