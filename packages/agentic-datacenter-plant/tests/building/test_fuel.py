"""The fuel oil system at fidelity F1 (SDD 6.3)."""

from typing import Any

import pytest

from agentic_datacenter.core.ports import ElectricalSupply, FuelDemand
from agentic_datacenter.plant.fuel import MODULE

LIVE = ElectricalSupply(True, 1.0, 1.0)
DEAD = ElectricalSupply(False, 0.0, 0.0)
TRAINS = ("A", "B", "C")
FULL_BURN = 430.0


def fuel(rig: Any, **params: Any) -> Any:
    r = rig(MODULE, params, keys={"trains": TRAINS})
    r.forward["power"] = LIVE
    for train in TRAINS:
        r.reverse[f"supply[{train}]"] = FuelDemand(litre_per_h=0.0)
    return r


def burn(r: Any, train: str, litre_per_h: float = FULL_BURN) -> None:
    r.reverse[f"supply[{train}]"] = FuelDemand(litre_per_h=litre_per_h)


def test_module_is_at_fidelity_one() -> None:
    assert MODULE.manifest.fidelity == "F1"


def test_at_rest_nothing_moves_and_fuel_is_available(rig: Any) -> None:
    r = fuel(rig)
    r.run(60)
    io = r.module.io
    assert io["bulk_litre"] == 50_000.0 and io["sub_a_level_pct"] == pytest.approx(90.0)
    assert io["sub_a_time_to_empty_h"] == 1000.0 and io["power_kw"] == 0.0
    assert all(r.out(f"supply[{t}]").available for t in TRAINS)
    assert r.module.settled()


def test_sub_base_tank_drains_with_generator_load_and_refills_between_the_switches(
    rig: Any,
) -> None:
    r = fuel(rig)
    burn(r, "A")
    io = r.module.io
    r.run(60)
    assert io["sub_a_level_pct"] < 90.0 and not io["sub_a_pump_running"]
    assert io["sub_a_time_to_empty_h"] == pytest.approx(4000.0 * 0.9 / FULL_BURN, rel=0.05)
    assert io["sub_b_level_pct"] == pytest.approx(90.0), "each generator has its own tank"
    r.until(lambda: bool(io["sub_a_pump_running"]), limit_s=6 * 3600)
    assert io["sub_a_level_pct"] == pytest.approx(50.0, abs=0.1), "starts at the low switch"
    assert r.back("power").kw == pytest.approx(1.5)
    assert io["sub_a_time_to_empty_h"] == 1000.0, "filling faster than it burns"
    r.until(lambda: not io["sub_a_pump_running"], limit_s=6 * 3600)
    assert io["sub_a_level_pct"] == pytest.approx(90.0, abs=0.1), "stops at the high switch"


def test_mass_is_conserved(rig: Any) -> None:
    r = fuel(rig)
    start = r.module.total_litre()
    burn(r, "A")
    burn(r, "B", 130.0)
    r.run(5 * 3600)
    burned = (FULL_BURN + 130.0) * 5.0
    assert r.module.total_litre() == pytest.approx(start - burned, rel=1e-6)
    assert r.module.io["bulk_litre"] < 50_000.0


def test_transfer_pump_failure_lets_the_tank_run_low_and_then_empty(rig: Any) -> None:
    r = fuel(rig)
    r.module.inject("transfer_pump_failure", train="B")
    burn(r, "B")
    io = r.module.io
    r.until(lambda: bool(io["alarm_sub_b_pump_fault"]), limit_s=6 * 3600)
    assert io["sub_b_level_pct"] == pytest.approx(50.0, abs=0.1) and not io["sub_b_pump_running"]
    r.until(lambda: bool(io["alarm_sub_b_low_level"]), limit_s=6 * 3600)
    assert io["sub_b_level_pct"] < 25.0
    hours_left = float(io["sub_b_time_to_empty_h"])
    assert hours_left == pytest.approx(4000.0 * 0.25 / FULL_BURN, rel=0.02)
    r.until(lambda: not r.out("supply[B]").available, limit_s=6 * 3600)
    assert io["sub_b_level_pct"] == 0.0 and io["sub_b_time_to_empty_h"] == 0.0
    assert r.out("supply[A]").available
    r.module.inject("transfer_pump_restore", train="B")
    burn(r, "B", 0.0)
    r.run(120)
    assert io["sub_b_pump_running"] and r.out("supply[B]").available


def test_level_switch_stuck_wet_never_refills(rig: Any) -> None:
    r = fuel(rig)
    r.module.inject("stuck_level_switch", train="A", state="wet")
    burn(r, "A")
    r.run(6 * 3600)
    io = r.module.io
    assert io["sub_a_level_pct"] < 40.0 and not io["sub_a_pump_running"]
    assert not io["alarm_sub_a_pump_fault"], "the controller never called the pump"
    r.module.inject("level_switch_clear", train="A")
    r.run(5)
    assert io["sub_a_pump_running"]


def test_level_switch_stuck_dry_overfills_until_the_high_high_switch_trips_the_pump(
    rig: Any,
) -> None:
    r = fuel(rig)
    r.module.inject("stuck_level_switch", train="C", state="dry")
    io = r.module.io
    r.until(lambda: bool(io["alarm_sub_c_overfill"]), limit_s=3600)
    assert io["sub_c_level_pct"] >= 98.0 and not io["sub_c_pump_running"]
    r.run(600)
    assert io["sub_c_level_pct"] <= 100.0 and io["alarm_sub_c_overfill"]


def test_interstitial_leak_stops_every_pump(rig: Any) -> None:
    r = fuel(rig)
    r.module.inject("set_level", train="A", pct=40.0)
    r.run(5)
    io = r.module.io
    assert io["sub_a_pump_running"]
    r.module.inject("interstitial_leak", location="BULK")
    r.run(5)
    assert io["alarm_leak"] and io["leak_location"] == "BULK"
    assert not io["sub_a_pump_running"] and r.back("power").kw == 0.0
    r.module.inject("leak_clear")
    r.run(5)
    assert io["sub_a_pump_running"] and not io["alarm_leak"]


def test_pumps_need_power_and_the_transfer_enable(rig: Any) -> None:
    r = fuel(rig)
    r.module.inject("set_level", train="A", pct=40.0)
    r.forward["power"] = DEAD
    r.run(5)
    io = r.module.io
    assert not io["sub_a_pump_running"] and not io["alarm_sub_a_pump_fault"]
    r.forward["power"] = LIVE
    io["transfer_enable"] = False
    r.run(5)
    assert not io["sub_a_pump_running"]
    io["transfer_enable"] = True
    r.run(5)
    assert io["sub_a_pump_running"]


def test_polishing_runs_on_its_schedule_and_moves_no_fuel(rig: Any) -> None:
    r = fuel(rig, polish_every_h=1.0, polish_for_h=0.25)
    r.run(3000)
    io = r.module.io
    assert not io["polishing"] and r.module.settled()
    r.run(598)
    assert not io["polishing"] and not r.module.settled(), "polishing is about to start"
    r.run(12)
    assert io["polishing"] and r.back("power").kw == pytest.approx(2.2)
    r.run(900)
    assert not io["polishing"] and io["bulk_litre"] == 50_000.0
    io["polish_enable"] = False
    r.run(3600 - 900 + 20)
    assert not io["polishing"]


def test_empty_bulk_storage_refills_nothing(rig: Any) -> None:
    r = fuel(rig)
    r.module.inject("set_bulk", pct=0.0)
    r.module.inject("set_level", train="A", pct=30.0)
    r.run(60)
    io = r.module.io
    assert not io["sub_a_pump_running"] and io["sub_a_level_pct"] == pytest.approx(30.0)


def test_only_the_enables_are_writable(rig: Any) -> None:
    r = fuel(rig)
    writable = {name for name in r.module.io if r.module.io.declaration(name).tier in ("T2", "T3")}
    assert writable == {"polish_enable", "transfer_enable"}


def test_unknown_train_and_bad_arguments_are_refused(rig: Any) -> None:
    r = fuel(rig)
    with pytest.raises(ValueError, match="train"):
        r.module.inject("transfer_pump_failure", train="Z")
    with pytest.raises(ValueError, match="state"):
        r.module.inject("stuck_level_switch", train="A", state="sideways")
    with pytest.raises(ValueError, match="location"):
        r.module.inject("interstitial_leak", location="ROOF")
