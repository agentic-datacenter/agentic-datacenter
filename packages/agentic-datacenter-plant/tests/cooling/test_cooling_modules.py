"""Cooling modules at fidelity F1, each driven alone."""

from typing import Any

import pytest

from agentic_datacenter.core.ports import (
    AirHeat,
    AirInlet,
    ElectricalDemand,
    ElectricalSupply,
    HydronicReturn,
    HydronicSupply,
    Signal,
    Weather,
)
from agentic_datacenter.plant.cooling.chw_plant import MODULE as CHW_PLANT
from agentic_datacenter.plant.cooling.eroom import MODULE as EROOM
from agentic_datacenter.plant.cooling.pod import MODULE as POD
from agentic_datacenter.plant.cooling.pump_station import MODULE as PUMPS
from agentic_datacenter.plant.cooling.tes import MODULE as TES
from agentic_datacenter.plant.cooling.weather import MODULE as WEATHER

LIVE = ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0)
DEAD = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)
COLD = HydronicSupply(available=True, supply_c=18.0)
CP_W = 4.186

# --- weather ---------------------------------------------------------------------


def test_weather_follows_a_daily_cycle_and_a_heat_wave(rig: Any) -> None:
    r = rig(WEATHER, {"dry_bulb_c": 20.0, "daily_swing_c": 6.0})
    r.run(1)
    values = []
    for _ in range(24):
        r.run(3600)
        values.append(r.out("ambient").dry_bulb_c)
    assert min(values) == pytest.approx(14.0, abs=0.3) and max(values) == pytest.approx(
        26.0, abs=0.3
    )
    r.module.inject("heat_wave", peak_c=40.0)
    r.run(1)
    assert r.out("ambient").dry_bulb_c > 30.0
    r.module.inject("set", dry_bulb_c=35.0)
    r.run(3600)
    assert r.out("ambient") == Weather(dry_bulb_c=35.0, rel_humidity_pct=50.0)


# --- POD ---------------------------------------------------------------------------


def pod(rig: Any, **params: Any) -> Any:
    r = rig(POD, params)
    r.forward = {
        "chw": COLD,
        "it_heat": AirHeat(150.0, 12.0),
        "fan_power": LIVE,
        "fan_power_b": LIVE,
        "fire_stop": Signal(False),
    }
    return r


def test_pod_starts_in_steady_state_at_its_supply_air_setpoint(rig: Any) -> None:
    r = pod(rig)
    r.run(600)
    io = r.module.io
    assert io["supply_air_c"] == pytest.approx(22.0, abs=0.05)
    assert io["coil_kw"] == pytest.approx(150.0 + io["fan_kw"], rel=0.01)
    assert r.back("it_heat") == AirInlet(inlet_c=io["supply_air_c"])
    assert r.back("chw").heat_kw == pytest.approx(io["coil_kw"])
    assert r.back("chw").flow_kg_s == pytest.approx(io["coil_kw"] / (CP_W * 8.0), rel=0.01)
    assert r.back("fan_power").kw == pytest.approx(6.0)


def test_pod_keeps_its_air_handlers_on_either_of_its_two_supplies(rig: Any) -> None:
    """One train lost must not stop the air handlers of a POD whose IT load stays on."""
    r = pod(rig)
    r.run(300)
    fan_kw = r.back("fan_power").kw
    assert fan_kw > 0.0 and r.back("fan_power_b").kw == 0.0
    r.forward["fan_power"] = DEAD
    r.run(600)
    assert r.module.io["fans_running"] is True and r.module.io["supply_air_c"] < 25.0
    assert r.back("fan_power").kw == 0.0 and r.back("fan_power_b").kw == pytest.approx(fan_kw)
    r.forward["fan_power_b"] = DEAD
    r.run(5)
    assert r.module.io["fans_running"] is False
    assert r.back("fan_power_b").kw == 0.0


@pytest.mark.req("ADC-PRC-004")
@pytest.mark.parametrize("lost", ["chilled_water", "fan_power", "both"])
def test_pod_with_all_cooling_lost_reaches_the_critical_threshold_in_3_to_6_minutes(
    rig: Any, lost: str
) -> None:
    r = pod(rig)
    r.run(300)
    if lost in ("chilled_water", "both"):
        r.forward["chw"] = HydronicSupply(available=False, supply_c=18.0)
    if lost in ("fan_power", "both"):
        r.forward["fan_power"] = r.forward["fan_power_b"] = DEAD
    took = r.until(lambda: r.module.io["supply_air_c"] >= 32.0, limit_s=1200)
    assert 180.0 <= took <= 360.0
    assert r.module.io["thermally_critical"] is False, "the flag needs 60 s above the threshold"
    r.run(61)
    assert r.module.io["thermally_critical"] is True
    assert r.module.io["critical_minutes"] > 0.0


def test_pod_recovers_when_cooling_returns(rig: Any) -> None:
    r = pod(rig)
    r.run(300)
    r.forward["chw"] = HydronicSupply(available=False, supply_c=18.0)
    r.run(120)
    assert r.module.io["supply_air_c"] > 25.0
    r.forward["chw"] = COLD
    r.run(1500)
    assert r.module.io["supply_air_c"] == pytest.approx(22.0, abs=0.3)
    assert r.module.io["thermally_critical"] is False


def test_pod_supply_air_follows_a_setpoint_change_without_overshooting_far(rig: Any) -> None:
    r = pod(rig)
    r.run(300)
    r.module.io["supply_air_sp_c"] = 24.0
    highest = 0.0
    for _ in range(1800):
        r.run(1)
        highest = max(highest, r.module.io["supply_air_c"])
    assert r.module.io["supply_air_c"] == pytest.approx(24.0, abs=0.2)
    assert highest < 24.8


def test_pod_runs_warmer_when_chilled_water_is_too_warm_for_its_coil(rig: Any) -> None:
    r = pod(rig)
    r.forward["chw"] = HydronicSupply(available=True, supply_c=24.0)
    r.run(3600)
    assert r.module.io["valve_pct"] == pytest.approx(100.0)
    assert r.module.io["supply_air_c"] > 23.0, "the coil cannot hold 22 degC with 24 degC water"


def test_confirmed_fire_stops_the_air_handlers(rig: Any) -> None:
    r = pod(rig)
    r.run(300)
    r.forward["fire_stop"] = Signal(True)
    r.run(5)
    assert r.module.io["fans_running"] is False and r.back("fan_power") == ElectricalDemand(0.0)
    assert r.back("chw") == HydronicReturn(flow_kg_s=0.0, heat_kw=0.0)


def test_pod_conserves_energy_through_a_loss_of_cooling(rig: Any) -> None:
    r = pod(rig)
    r.run(60)
    start = r.module.heat_balance()
    r.forward["chw"] = HydronicSupply(available=False, supply_c=18.0)
    r.run(200)
    r.forward["chw"] = COLD
    r.run(400)
    end = r.module.heat_balance()
    gained = end["in_kwh"] - start["in_kwh"]
    removed = end["out_kwh"] - start["out_kwh"]
    stored = end["stored_kwh"] - start["stored_kwh"]
    assert gained == pytest.approx(removed + stored, rel=1e-6)


# --- electrical room ---------------------------------------------------------------


def test_electrical_room_holds_its_return_air_setpoint(rig: Any) -> None:
    r = rig(EROOM)
    r.forward = {"chw": COLD, "ups_heat": AirHeat(33.0, 4.0), "power": LIVE}
    r.run(1800)
    io = r.module.io
    assert io["room_c"] == pytest.approx(24.0, abs=0.2)
    assert r.back("chw").heat_kw == pytest.approx(33.0 + io["fan_kw"], rel=0.02)
    assert r.back("ups_heat") == AirInlet(inlet_c=io["room_c"])
    r.forward["chw"] = HydronicSupply(False, 18.0)
    r.run(600)
    assert io["room_c"] > 27.0, "the room warms without water"


# --- pump station ------------------------------------------------------------------


def pumps(rig: Any) -> Any:
    r = rig(PUMPS)
    r.forward = {"chws_in": COLD, "power_1": LIVE, "power_2": LIVE, "power_3": LIVE}
    r.reverse = {"chw": HydronicReturn(flow_kg_s=79.0, heat_kw=2650.0)}
    return r


def test_two_duty_pumps_run_and_the_standby_takes_over_on_a_fault(rig: Any) -> None:
    r = pumps(rig)
    r.run(60)
    io = r.module.io
    assert [io[f"p{n}_running"] for n in (1, 2, 3)] == [True, True, False]
    assert r.out("chw").available and r.out("chw").supply_c == pytest.approx(18.0, abs=0.05)
    power = io["power_kw"]
    assert 30.0 < power < 60.0
    assert r.back("chws_in").flow_kg_s == pytest.approx(79.0)
    assert r.back("chws_in").heat_kw == pytest.approx(2650.0 + power), (
        "pump power ends up in the water"
    )
    r.module.inject("pump_fail", pump=1)
    r.run(5)
    assert [io[f"p{n}_running"] for n in (1, 2, 3)] == [False, True, True]
    assert r.back("power_1") == ElectricalDemand(0.0) and r.back("power_3").kw > 0.0


def test_pump_power_follows_the_cube_of_speed(rig: Any) -> None:
    r = pumps(rig)
    r.run(60)
    full = r.module.io["power_kw"]
    r.reverse["chw"] = HydronicReturn(flow_kg_s=79.0 * 0.7, heat_kw=1800.0)
    r.module.io["dp_sp_kpa"] = 60.0
    r.run(120)
    ratio = (r.module.io["speed_pct"] / 100.0) ** 3 / (0.88**3)
    assert r.module.io["power_kw"] == pytest.approx(full * ratio, rel=0.05)
    assert r.module.io["power_kw"] < 0.5 * full


def test_differential_pressure_setpoint_sets_a_floor_on_speed(rig: Any) -> None:
    r = pumps(rig)
    r.reverse["chw"] = HydronicReturn(flow_kg_s=20.0, heat_kw=600.0)
    r.run(120)
    low_flow = r.module.io["power_kw"]
    r.module.io["dp_sp_kpa"] = 80.0
    r.run(120)
    assert r.module.io["power_kw"] < low_flow, "a lower setpoint saves pump energy at part load"


def test_no_running_pump_means_no_chilled_water(rig: Any) -> None:
    r = pumps(rig)
    r.run(10)
    r.forward.update({"power_1": DEAD, "power_2": DEAD, "power_3": DEAD})
    r.run(5)
    assert not r.out("chw").available
    assert r.back("chws_in") == HydronicReturn(flow_kg_s=0.0, heat_kw=0.0)


def test_one_pump_alone_delivers_warmer_water_at_design_flow(rig: Any) -> None:
    r = pumps(rig)
    r.run(10)
    r.forward.update({"power_2": DEAD, "power_3": DEAD})
    r.run(120)
    assert r.out("chw").available
    assert r.out("chw").supply_c > 20.0, "short of flow, so the loop runs warmer"


# --- thermal storage ---------------------------------------------------------------


def tes(rig: Any) -> Any:
    r = rig(TES)
    r.forward = {"chws_in": COLD}
    r.reverse = {"chws_out": HydronicReturn(flow_kg_s=79.0, heat_kw=2650.0)}
    return r


def test_full_tank_passes_water_and_heat_straight_through(rig: Any) -> None:
    r = tes(rig)
    r.run(60)
    assert r.out("chws_out") == COLD and r.module.io["charge_pct"] == 100.0
    assert r.back("chws_in") == HydronicReturn(flow_kg_s=79.0, heat_kw=2650.0)


def test_tank_covers_about_ten_minutes_of_design_load_with_the_chillers_off(rig: Any) -> None:
    r = tes(rig)
    r.run(10)
    # Chillers off: the water arrives uncooled, at return temperature.
    r.forward["chws_in"] = HydronicSupply(True, 18.0 + 2650.0 / (79.0 * CP_W))
    lasted = r.until(lambda: r.module.io["charge_pct"] == 0.0, limit_s=3600)
    assert 480.0 <= lasted <= 720.0
    r.run(5)
    assert r.module.io["discharging"] is False
    assert r.out("chws_out").supply_c == pytest.approx(26.0, abs=0.1), "empty: no more cooling"


def test_tank_holds_supply_temperature_while_it_discharges(rig: Any) -> None:
    r = tes(rig)
    r.run(10)
    r.forward["chws_in"] = HydronicSupply(True, 22.0)
    r.run(60)
    assert r.out("chws_out").supply_c == pytest.approx(18.0, abs=0.01)
    assert r.module.io["discharging"] is True
    assert r.back("chws_in").heat_kw == pytest.approx(2650.0 - 79.0 * CP_W * 4.0, rel=0.01)


def test_tank_recharges_at_a_limited_rate_once_the_plant_holds_its_setpoint(rig: Any) -> None:
    r = tes(rig)
    r.module.inject("set_charge", pct=50.0)
    r.run(120)
    assert r.module.io["recharging"] is True
    assert r.back("chws_in").heat_kw == pytest.approx(2650.0 + 250.0)
    before = r.module.io["charge_pct"]
    r.run(600)
    gained_kwh = (r.module.io["charge_pct"] - before) / 100.0 * r.module.capacity_kwh
    assert gained_kwh == pytest.approx(250.0 * 600 / 3600, rel=0.02)


# --- chilled water plant -----------------------------------------------------------


def plant(rig: Any, heat_kw: float = 2650.0, ambient_c: float = 35.0) -> Any:
    r = rig(CHW_PLANT)
    r.forward = {
        "ambient": Weather(ambient_c, 50.0),
        "power_1": LIVE,
        "power_2": LIVE,
        "power_3": LIVE,
    }
    r.reverse = {"chws": HydronicReturn(flow_kg_s=heat_kw / (CP_W * 8.0), heat_kw=heat_kw)}
    return r


def test_two_chillers_carry_the_design_load_at_setpoint_with_one_in_standby(rig: Any) -> None:
    r = plant(rig)
    r.run(1800)
    io = r.module.io
    assert [io[f"ch{n}_state"] for n in (1, 2, 3)] == ["RUNNING", "RUNNING", "OFF"]
    assert r.out("chws").supply_c == pytest.approx(18.0, abs=0.05)
    assert io["cooling_kw"] == pytest.approx(2650.0, rel=0.005)
    assert io["power_kw"] == pytest.approx(600.0, rel=0.05), "about 600 kW electrical at design"
    assert r.back("power_1").kw == pytest.approx(r.back("power_2").kw)
    assert r.back("power_3") == ElectricalDemand(0.0)


def test_chiller_efficiency_improves_in_cooler_weather(rig: Any) -> None:
    hot, mild = plant(rig, ambient_c=35.0), plant(rig, ambient_c=20.0)
    hot.run(600)
    mild.run(600)
    assert mild.module.io["power_kw"] < 0.85 * hot.module.io["power_kw"]


def test_standby_chiller_starts_when_a_running_one_trips(rig: Any) -> None:
    r = plant(rig)
    r.run(60)
    r.module.inject("chiller_trip", chiller=1)
    r.run(2)
    assert r.module.io["ch1_state"] == "TRIPPED" and r.module.io["ch3_state"] == "STARTING"
    r.run(120)
    assert r.module.io["ch3_state"] == "RUNNING"
    assert r.out("chws").supply_c > 18.2, "the loop warmed while one chiller carried the load"
    r.run(1800)
    assert r.out("chws").supply_c == pytest.approx(18.0, abs=0.1)


def test_chiller_is_locked_out_for_180_s_after_a_power_interruption(rig: Any) -> None:
    r = plant(rig)
    r.run(60)
    r.forward["power_1"] = DEAD
    r.run(5)
    assert r.module.io["ch1_state"] == "LOCKED_OUT"
    r.forward["power_1"] = LIVE
    r.run(170)
    assert r.module.io["ch1_state"] == "LOCKED_OUT"
    r.run(15)
    assert r.module.io["ch1_state"] in ("OFF", "STARTING", "RUNNING")


def test_plant_stages_up_above_85_percent_for_five_minutes_and_down_below_50(rig: Any) -> None:
    r = plant(rig, heat_kw=3000.0)
    r.run(290)
    assert r.module.io["ch3_state"] == "OFF"
    r.run(120)
    assert r.module.io["ch3_state"] in ("STARTING", "RUNNING")
    r.reverse["chws"] = HydronicReturn(flow_kg_s=30.0, heat_kw=1000.0)
    r.run(890)
    assert sum(r.module.io[f"ch{n}_state"] == "RUNNING" for n in (1, 2, 3)) == 3
    r.run(1900)
    assert sum(r.module.io[f"ch{n}_state"] == "RUNNING" for n in (1, 2, 3)) == 1


def test_with_every_chiller_off_the_water_leaves_at_return_temperature(rig: Any) -> None:
    r = plant(rig)
    r.run(60)
    for n in (1, 2, 3):
        r.module.inject("chiller_trip", chiller=n)
    r.run(3600)
    assert r.module.io["cooling_kw"] == 0.0 and r.module.io["power_kw"] == 0.0
    assert r.out("chws").supply_c > 30.0, "all returned heat stays in the loop water"


def test_chilled_water_setpoint_is_followed(rig: Any) -> None:
    r = plant(rig)
    r.run(60)
    r.module.io["chws_sp_c"] = 20.0
    r.run(1800)
    assert r.out("chws").supply_c == pytest.approx(20.0, abs=0.05)


def test_plant_conserves_energy_through_a_trip_and_recovery(rig: Any) -> None:
    r = plant(rig)
    r.run(60)
    start = r.module.heat_balance()
    r.module.inject("chiller_trip", chiller=2)
    r.run(900)
    end = r.module.heat_balance()
    assert end["in_kwh"] - start["in_kwh"] == pytest.approx(
        end["out_kwh"] - start["out_kwh"] + end["stored_kwh"] - start["stored_kwh"], rel=1e-6
    )
