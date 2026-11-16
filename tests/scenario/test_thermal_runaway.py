"""ADC-PRC-004 on the whole plant, and what thermal storage buys."""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel

REPO = Path(__file__).resolve().parents[2]
PODS = [f"{n:02d}" for n in range(1, 17)]


def start() -> tuple[Kernel, Any]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    kernel.run_for(600_000)
    return kernel, plant


def seconds_until(kernel: Kernel, condition: Any, limit_s: int) -> float:
    start_ms = kernel.clock.now_ms
    while not condition():
        assert kernel.clock.now_ms - start_ms < limit_s * 1000, "condition not reached"
        kernel.run_for(1000)
    return (kernel.clock.now_ms - start_ms) / 1000


@pytest.mark.req("ADC-PRC-004")
def test_every_pod_reaches_the_critical_threshold_in_3_to_6_minutes_without_chilled_water() -> None:
    kernel, plant = start()
    pods = [plant.module("cooling.pod", p) for p in PODS]
    for pump in (1, 2, 3):
        plant.module("cooling.pump_station", "PHPS").inject("pump_fail", pump=pump)
    first = seconds_until(kernel, lambda: any(p.io["supply_air_c"] >= 32.0 for p in pods), 900)
    last = seconds_until(kernel, lambda: all(p.io["supply_air_c"] >= 32.0 for p in pods), 900)
    assert 180.0 <= first and first + last <= 360.0
    kernel.run_for(70_000)
    assert all(p.io["thermally_critical"] for p in pods)


def test_thermal_storage_carries_the_plant_through_a_loss_of_every_chiller() -> None:
    kernel, plant = start()
    pods = [plant.module("cooling.pod", p) for p in PODS]
    tank = plant.module("cooling.tes", "TES-1")
    for chiller in (1, 2, 3):
        plant.module("cooling.chw_plant", "CHW").inject("chiller_trip", chiller=chiller)
    kernel.run_for(8 * 60 * 1000)
    # The loop water warms toward return temperature first, so the tank is not
    # asked for the whole load from the first second.
    assert tank.io["charge_pct"] < 65.0, "the tank is doing the cooling"
    assert max(p.io["supply_air_c"] for p in pods) < 23.0, "and the PODs do not notice"
    took = seconds_until(kernel, lambda: any(p.io["thermally_critical"] for p in pods), 3600)
    assert took > 5 * 60, "with the tank empty, loop and halls still take minutes to warm"
