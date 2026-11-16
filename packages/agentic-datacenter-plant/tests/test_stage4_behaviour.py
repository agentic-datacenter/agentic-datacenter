"""Stage 4 behaviour of single modules: IT fans, workload traces, air handlers, reboot."""

import importlib.util
from pathlib import Path
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
from agentic_datacenter.plant.cooling.pod import MODULE as POD
from agentic_datacenter.plant.cooling.pump_station import MODULE as PUMPS
from agentic_datacenter.plant.electrical.it_load import MODULE as IT_LOAD
from agentic_datacenter.plant.electrical.power_train import MODULE as POWER_TRAIN

_spec = importlib.util.spec_from_file_location(
    "stage4_rig", Path(__file__).parent / "electrical" / "rig.py"
)
assert _spec and _spec.loader
_rig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_rig)
Rig = _rig.ModuleRig

LIVE = ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0)
DEAD = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)
COLD = HydronicSupply(available=True, supply_c=18.0)


# --- IT fans and workload -------------------------------------------------------


def it_load(inlet_c: float, **params: Any) -> Any:
    r = Rig(IT_LOAD, {"design_kw": 150.0, **params})
    r.forward = {"feed_a": LIVE, "feed_b": LIVE, "epo": Signal(False)}
    r.reverse = {"heat": AirInlet(inlet_c)}
    r.run(5)
    return r


@pytest.mark.req("ADC-FID-003")
def test_it_fan_power_rises_monotonically_with_inlet_temperature() -> None:
    temps = [15.0 + 0.5 * k for k in range(61)]
    fans = [it_load(t).module.io["fan_kw"] for t in temps]
    assert all(b >= a for a, b in zip(fans, fans[1:], strict=False))
    above = [f for t, f in zip(temps, fans, strict=True) if t >= 25.0]
    assert all(b > a for a, b in zip(above, above[1:], strict=False)), "strictly above 25 degC"
    assert fans[temps.index(35.0)] > 3.0 * fans[temps.index(25.0)]


@pytest.mark.req("ADC-FID-003")
def test_a_warmer_inlet_costs_power_and_moves_more_air() -> None:
    cool, warm = it_load(22.0), it_load(30.0)
    assert cool.module.io["served_kw"] == pytest.approx(150.0), "design load at the design inlet"
    assert warm.module.io["served_kw"] > cool.module.io["served_kw"] + 2.0
    assert warm.out("heat").airflow_kg_s > cool.out("heat").airflow_kg_s
    assert warm.out("heat").heat_kw == pytest.approx(warm.module.io["served_kw"])


def test_diurnal_trace_follows_a_daily_cycle() -> None:
    r = it_load(22.0, trace="diurnal")
    values = []
    for _ in range(24):
        r.run(3600)
        values.append(r.module.io["demand_kw"])
    assert max(values) == pytest.approx(150.0, rel=0.02)
    assert min(values) == pytest.approx(0.5 * 150.0, rel=0.05)


def test_accelerated_compute_trace_makes_large_fast_steps_and_is_seeded() -> None:
    def trace(seed: int) -> list[float]:
        r = Rig(IT_LOAD, {"design_kw": 150.0, "trace": "accelerated"}, seed=seed)
        r.forward = {"feed_a": LIVE, "feed_b": LIVE, "epo": Signal(False)}
        r.reverse = {"heat": AirInlet(22.0)}
        out = []
        for _ in range(3600):
            r.run(1)
            out.append(r.module.io["demand_kw"])
        return out

    first, again, other = trace(1), trace(1), trace(2)
    assert first == again and first != other
    steps = [abs(b - a) for a, b in zip(first, first[1:], strict=False)]
    assert max(steps) > 0.2 * 150.0, "a swing of more than 20 % of design in one second"
    assert 0.35 * 150.0 <= min(first) and max(first) <= 150.0 * 1.001


# --- air handlers ----------------------------------------------------------------


def pod() -> Any:
    r = Rig(POD)
    r.forward = {
        "chw": COLD,
        "it_heat": AirHeat(150.0, 12.0),
        "fan_power": LIVE,
        "fan_power_b": LIVE,
        "fire_stop": Signal(False),
    }
    r.run(300)
    return r


def test_four_air_handlers_share_the_airflow_at_three_quarter_speed() -> None:
    r = pod()
    io = r.module.io
    assert io["ahu_running"] == 4 and io["fan_speed_pct"] == pytest.approx(75.0, abs=0.5)
    assert io["fan_kw"] == pytest.approx(6.0, rel=0.02)
    assert io["static_pressure_pa"] == pytest.approx(50.0, abs=0.5)


def test_op05_air_handler_failure_remaining_units_ramp_and_static_pressure_recovers() -> None:
    r = pod()
    r.module.inject("ahu_fail", unit=2)
    lowest, hottest = 100.0, 0.0
    for _ in range(120):
        r.run(1)
        lowest = min(lowest, r.module.io["static_pressure_pa"])
        hottest = max(hottest, r.module.io["supply_air_c"])
    io = r.module.io
    assert io["ahu_running"] == 3 and io["fan_speed_pct"] == pytest.approx(100.0, abs=0.5)
    assert lowest < 40.0, "pressure dipped while the others ramped"
    assert io["static_pressure_pa"] == pytest.approx(50.0, abs=1.0), "and recovered"
    assert io["fan_kw"] > 9.0, "three units at full speed draw more than four at part speed"
    assert hottest < 25.0 and io["thermally_critical"] is False
    r.run(900)
    assert io["supply_air_c"] == pytest.approx(22.0, abs=0.3)


def test_two_failed_air_handlers_leave_the_pod_short_of_air() -> None:
    r = pod()
    r.module.inject("ahu_fail", unit=1)
    r.module.inject("ahu_fail", unit=2)
    r.run(1800)
    io = r.module.io
    assert io["static_pressure_pa"] < 30.0
    assert io["supply_air_c"] > 23.0, "exhaust air recirculates to the inlets"


def test_static_pressure_setpoint_trades_fan_power_for_airflow_margin() -> None:
    r = pod()
    base = r.module.io["fan_kw"]
    r.module.io["static_pressure_sp_pa"] = 70.0
    r.run(120)
    assert r.module.io["static_pressure_pa"] == pytest.approx(70.0, abs=1.5)
    assert r.module.io["fan_kw"] > 1.4 * base


# --- controller reboot -------------------------------------------------------------


def power_train() -> tuple[Any, Any, Any]:
    r = Rig(POWER_TRAIN)
    r.forward = {
        "utility_feed": LIVE,
        "gen_output": DEAD,
        "gen_ready_to_load": Signal(False),
        "gen_fault": Signal(False),
    }
    r.reverse = {"lv_bus": ElectricalDemand(500.0), "gen_start_request": None}
    r.run(5)

    def stimulate() -> None:
        r.forward["utility_feed"] = DEAD

    return r, stimulate, lambda: r.module.io["state"] != "ON_UTILITY"


def pod_loop() -> tuple[Any, Any, Any]:
    r = pod()
    start = r.module.io["valve_pct"]

    def stimulate() -> None:
        r.module.io["supply_air_sp_c"] = 26.0

    return r, stimulate, lambda: abs(r.module.io["valve_pct"] - start) > 0.5


def chillers() -> tuple[Any, Any, Any]:
    r = Rig(CHW_PLANT)
    r.forward = {"ambient": Weather(35.0, 50.0), "power_1": LIVE, "power_2": LIVE, "power_3": LIVE}
    r.reverse = {"chws": HydronicReturn(79.0, 2650.0)}
    r.run(30)

    def stimulate() -> None:
        r.module.inject("chiller_trip", chiller=1)

    return r, stimulate, lambda: r.module.io["ch3_state"] != "OFF"


def pumps() -> tuple[Any, Any, Any]:
    r = Rig(PUMPS)
    r.forward = {"chws_in": COLD, "power_1": LIVE, "power_2": LIVE, "power_3": LIVE}
    r.reverse = {"chw": HydronicReturn(79.0, 2650.0)}
    r.run(30)

    def stimulate() -> None:
        r.module.inject("pump_fail", pump=1)

    return r, stimulate, lambda: bool(r.module.io["p3_running"])


@pytest.mark.req("ADC-CTL-005")
@pytest.mark.parametrize("build", [power_train, pod_loop, chillers, pumps])
@pytest.mark.parametrize(("kind", "seconds"), [("warm", 60), ("cold", 180)])
def test_controller_reboot_takes_its_time_and_holds_its_outputs_meanwhile(
    build: Any, kind: str, seconds: int
) -> None:
    r, stimulate, reacted = build()
    r.module.inject("reboot", kind=kind)
    r.run(1)
    assert not r.module.ctx.controller_running()
    stimulate()
    r.run(seconds - 3)
    assert not r.module.ctx.controller_running()
    assert not reacted(), "the controller is down: its outputs stay where they were"
    r.run(4)
    assert r.module.ctx.controller_running()
    r.run(15)
    assert reacted(), "back up, it acts on what happened meanwhile"


@pytest.mark.req("ADC-CTL-005")
def test_the_interlock_still_holds_while_the_transfer_controller_reboots() -> None:
    r, _, _ = power_train()
    r.module.inject("reboot", kind="cold")
    r.module.inject("manual_close", breaker="gen")
    r.run(30)
    assert r.module.io["util_brk_closed"] is True and r.module.io["gen_brk_closed"] is False


@pytest.mark.req("ADC-CTL-005")
def test_process_keeps_running_while_a_pod_controller_reboots() -> None:
    r = pod()
    r.module.inject("reboot", kind="warm")
    r.run(30)
    assert r.module.io["fans_running"] is True and r.module.io["coil_kw"] > 100.0
    assert r.module.io["supply_air_c"] == pytest.approx(22.0, abs=0.3)


def test_unknown_reboot_kind_is_refused() -> None:
    r = pod()
    with pytest.raises(Exception, match="lukewarm"):
        r.module.inject("reboot", kind="lukewarm")
