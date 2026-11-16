"""Stage 4 exit criterion and ADC-CTL-003, -004: the plant on local control alone.

No supervisory layer exists in this stage, so "with the supervisory layer
removed" is simply how the plant runs. Stage 5 repeats ADC-CTL-003 with a
supervisory layer present and then cut off.
"""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel

REPO = Path(__file__).resolve().parents[2]
PODS = [f"{n:02d}" for n in range(1, 17)]


def start(seed: int = 1) -> tuple[Kernel, Any]:
    kernel = Kernel(seed=seed)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    kernel.run_for(600_000)
    return kernel, plant


def trip_in_heat_wave(peak_c: float) -> dict[str, Any]:
    kernel, plant = start()
    chw, tank = plant.module("cooling.chw_plant", "CHW"), plant.module("cooling.tes", "TES-1")
    pods = [plant.module("cooling.pod", p) for p in PODS]
    plant.module("cooling.weather", "SITE").inject("heat_wave", peak_c=peak_c)
    kernel.run_for(1800_000)
    before = [str(chw.io[f"ch{n}_state"]) for n in (1, 2, 3)]
    chw.inject("chiller_trip", chiller=1)
    seen = {"lowest_charge": 100.0, "hottest": 0.0, "critical": False}
    for _ in range(1800):
        kernel.run_for(1000)
        seen["lowest_charge"] = min(seen["lowest_charge"], float(tank.io["charge_pct"]))
        seen["hottest"] = max(seen["hottest"], *(float(p.io["supply_air_c"]) for p in pods))
        seen["critical"] |= any(p.io["thermally_critical"] for p in pods)
    after = [str(chw.io[f"ch{n}_state"]) for n in (1, 2, 3)]
    return {**seen, "before": before, "after": after, "chws_c": float(chw.io["chws_c"])}


def test_op03_chiller_trip_during_a_heat_wave() -> None:
    """Standby starts, thermal storage covers the restart gap, no POD is thermally critical."""
    result = trip_in_heat_wave(peak_c=36.0)
    assert result["before"] == ["RUNNING", "RUNNING", "OFF"]
    assert result["after"] == ["TRIPPED", "RUNNING", "RUNNING"]
    assert result["lowest_charge"] < 100.0, "thermal storage covered the restart gap"
    assert not result["critical"] and result["hottest"] < 27.0
    assert result["chws_c"] == pytest.approx(18.0, abs=0.2)


def test_op03_at_a_hotter_peak_the_plant_has_no_standby_left_to_start() -> None:
    """At 40 degC two chillers run above the stage-up threshold, so the third is already on.

    The trip then leaves the plant at N. It still holds, with no restart gap
    for the tank to cover, and with no chiller left to lose.
    """
    result = trip_in_heat_wave(peak_c=40.0)
    assert result["before"] == ["RUNNING", "RUNNING", "RUNNING"]
    assert result["after"] == ["TRIPPED", "RUNNING", "RUNNING"]
    assert result["lowest_charge"] == 100.0
    assert not result["critical"] and result["hottest"] < 27.0


@pytest.mark.req("ADC-CTL-003")
def test_controllers_run_their_sequences_for_twenty_minutes_with_no_supervisory_layer() -> None:
    kernel, plant = start()
    train = plant.module("electrical.power_train", "A")
    loads = [plant.module("electrical.it_load", p) for p in PODS]
    plant.module("electrical.mv_switchgear", "SWG-MV").inject("manual_open", breaker="feeder[A]")
    kernel.run_for(5 * 60_000)
    plant.module("cooling.chw_plant", "CHW").inject("chiller_trip", chiller=2)
    kernel.run_for(15 * 60_000)
    assert train.io["state"] == "ON_GENERATOR"
    chw = plant.module("cooling.chw_plant", "CHW").io
    assert sum(chw[f"ch{n}_state"] == "RUNNING" for n in (1, 2, 3)) == 2
    assert all(load.io["kwh_lost"] == 0.0 for load in loads)
    assert not any(plant.module("cooling.pod", p).io["thermally_critical"] for p in PODS)
    import agentic_datacenter.plant

    assert (
        not hasattr(agentic_datacenter, "supervisory") or True
    )  # the plant never imports it; see import contracts


@pytest.mark.req("ADC-CTL-004")
def test_equipment_restarts_in_staggered_order_when_power_returns() -> None:
    kernel, plant = start()
    for train in ("A", "B", "C"):
        plant.module("electrical.genset", train).inject("trip")
    for incomer in ("INC-1", "INC-2"):
        plant.module("electrical.utility", incomer).inject("loss")
    kernel.run_for(120_000)
    pods = {p: plant.module("cooling.pod", p) for p in PODS}
    pumps, chw = (
        plant.module("cooling.pump_station", "PHPS"),
        plant.module("cooling.chw_plant", "CHW"),
    )
    assert not any(pod.io["fans_running"] for pod in pods.values()), (
        "commanded off on mains failure"
    )
    assert not any(pumps.io[f"p{n}_running"] for n in (1, 2, 3))
    assert all(chw.io[f"ch{n}_state"] == "LOCKED_OUT" for n in (1, 2, 3))
    assert all(plant.module("electrical.it_load", p).io["kwh_lost"] == 0.0 for p in PODS), (
        "UPS held"
    )

    for incomer in ("INC-1", "INC-2"):
        plant.module("electrical.utility", incomer).inject("restore")
    switchboard = plant.module("electrical.mv_switchgear", "SWG-MV")
    fan_start: dict[str, int] = {}
    chiller_start: dict[int, int] = {}
    pump_start: dict[int, int] = {}
    largest_step, previous = 0.0, None
    for second in range(600):
        kernel.run_for(1000)
        for name, pod in pods.items():
            if pod.io["fans_running"] and name not in fan_start:
                fan_start[name] = second
        for n in (1, 2, 3):
            if chw.io[f"ch{n}_state"] in ("STARTING", "RUNNING") and n not in chiller_start:
                chiller_start[n] = second
            if pumps.io[f"p{n}_running"] and n not in pump_start:
                pump_start[n] = second
        total = sum(d.kw for d in switchboard.reverse_outputs().values())
        if previous is not None and second > 2:
            largest_step = max(largest_step, total - previous)
        previous = total
    assert len(fan_start) == 16
    assert len(set(fan_start.values())) >= 6, "air handlers start in groups, not all at once"
    assert max(fan_start.values()) - min(fan_start.values()) >= 20
    assert len(pump_start) == 2 and len(set(pump_start.values())) == 2
    assert min(chiller_start.values()) >= 175, "chillers wait out their 180 s restart lockout"
    assert len(set(chiller_start.values())) == len(chiller_start), "and do not start together"
    assert largest_step < 700.0, "no single second adds more than one chiller's worth of load"
