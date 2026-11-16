"""ADC-PRC-002: thermal energy is conserved across the chilled water loop and the tank.

Over any one-hour window, the heat the consumers and the pumps put into the
water equals the heat the chillers removed, plus what the loop water and the
tank took up, within 1 %.
"""

from pathlib import Path

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel

REPO = Path(__file__).resolve().parents[2]
PODS = [f"{n:02d}" for n in range(1, 17)]
EVENTS = [
    ("cooling.chw_plant", "CHW", "chiller_trip", {"chiller": 1}),
    ("cooling.chw_plant", "CHW", "chiller_trip", {"chiller": 2}),
    ("cooling.chw_plant", "CHW", "chiller_reset", {"chiller": 1}),
    ("cooling.chw_plant", "CHW", "chiller_reset", {"chiller": 2}),
    ("cooling.pump_station", "PHPS", "pump_fail", {"pump": 1}),
    ("cooling.pump_station", "PHPS", "pump_restore", {"pump": 1}),
    ("cooling.weather", "SITE", "heat_wave", {"peak_c": 42.0}),
    ("cooling.weather", "SITE", "clear", {}),
    ("cooling.tes", "TES-1", "set_charge", {"pct": 30.0}),
    ("electrical.it_load", "03", "set_load", {"fraction": 0.5}),
    ("electrical.it_load", "03", "set_load", {"fraction": 1.0}),
    ("electrical.utility", "INC-1", "loss", {}),
    ("electrical.utility", "INC-1", "restore", {}),
]


@pytest.mark.req("ADC-PRC-002")
@pytest.mark.parametrize("seed", [1, 2, 3])
def test_loop_and_tank_conserve_energy_over_every_one_hour_window(seed: int) -> None:
    kernel = Kernel(seed=seed)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    order = kernel.rng.stream("test.events")
    consumers = [plant.module("cooling.pod", p) for p in PODS]
    consumers += [plant.module("cooling.eroom", t) for t in ("A", "B", "C")]
    pumps = plant.module("cooling.pump_station", "PHPS")
    tank = plant.module("cooling.tes", "TES-1")
    chillers = plant.module("cooling.chw_plant", "CHW")
    samples = []
    for minute in range(180):
        if minute % 7 == 3:
            module_id, instance, fault, params = EVENTS[order.randrange(len(EVENTS))]
            target = plant.module(module_id, instance)
            target.inject(fault, **params)
            if fault == "set_charge":
                samples.clear()  # the scenario changed the stored energy by hand
        kernel.run_for(60_000)
        plant_balance, tank_balance = chillers.heat_balance(), tank.heat_balance()
        samples.append(
            {
                "into_water": sum(c.heat_balance()["out_kwh"] for c in consumers)
                + pumps.pump_heat_kwh(),
                "removed": plant_balance["out_kwh"],
                "held": plant_balance["stored_kwh"] + tank_balance["stored_kwh"],
            }
        )
    windows = 0
    for now, hour_ago in zip(samples[60:], samples, strict=False):
        into_water = now["into_water"] - hour_ago["into_water"]
        accounted = now["removed"] - hour_ago["removed"] + now["held"] - hour_ago["held"]
        assert accounted == pytest.approx(into_water, rel=0.01), (seed, windows)
        windows += 1
    assert windows > 0
