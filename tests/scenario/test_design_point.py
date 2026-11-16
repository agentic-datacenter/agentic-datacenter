"""ADC-PRC-010: steady state at 100 % IT load reproduces the design balance of SDD section 3.

IT 2,400 kW; chillers about 600 kW electrical; pumps, fans and losses about
250 kW; total about 3,250 kW; PUE about 1.35. Each within 5 %, at the design
ambient temperature.
"""

from pathlib import Path

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel

REPO = Path(__file__).resolve().parents[2]
PODS = [f"{n:02d}" for n in range(1, 17)]
TRAINS = ("A", "B", "C")


@pytest.mark.req("ADC-PRC-010")
def test_design_point_balance_within_five_percent() -> None:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    plant.module("cooling.weather", "SITE").inject("set", dry_bulb_c=35.0)
    kernel.run_for(2 * 3600 * 1000)

    it_kw = sum(plant.module("electrical.it_load", p).io["served_kw"] for p in PODS)
    chillers_kw = plant.module("cooling.chw_plant", "CHW").io["power_kw"]
    switchboard = plant.module("electrical.mv_switchgear", "SWG-MV")
    total_kw = sum(d.kw for d in switchboard.reverse_outputs().values())
    other_kw = total_kw - it_kw - chillers_kw
    ups_loss = sum(plant.module("electrical.ups", t).io["loss_kw"] for t in TRAINS)
    fans = sum(plant.module("cooling.pod", p).io["fan_kw"] for p in PODS)
    fans += sum(plant.module("cooling.eroom", t).io["fan_kw"] for t in TRAINS)
    pumps = plant.module("cooling.pump_station", "PHPS").io["power_kw"]

    assert it_kw == pytest.approx(2400.0, rel=0.05)
    assert chillers_kw == pytest.approx(600.0, rel=0.05)
    assert other_kw == pytest.approx(250.0, rel=0.05)
    assert total_kw == pytest.approx(3250.0, rel=0.05)
    assert total_kw / it_kw == pytest.approx(1.35, rel=0.05)
    # The "other" share is exactly UPS losses, fans and pumps: nothing is unaccounted for.
    assert other_kw == pytest.approx(ups_loss + fans + pumps, rel=1e-6)


@pytest.mark.req("ADC-PRC-010")
def test_design_point_is_a_steady_state_with_n_plus_1_margin() -> None:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    plant.module("cooling.weather", "SITE").inject("set", dry_bulb_c=35.0)
    kernel.run_for(2 * 3600 * 1000)
    chw = plant.module("cooling.chw_plant", "CHW").io
    assert [chw[f"ch{n}_state"] for n in (1, 2, 3)] == ["RUNNING", "RUNNING", "OFF"]
    assert chw["chws_c"] == pytest.approx(18.0, abs=0.1)
    pumps = plant.module("cooling.pump_station", "PHPS").io
    assert [pumps[f"p{n}_running"] for n in (1, 2, 3)] == [True, True, False]
    assert plant.module("cooling.tes", "TES-1").io["charge_pct"] == 100.0
    for pod in PODS:
        io = plant.module("cooling.pod", pod).io
        assert io["supply_air_c"] == pytest.approx(22.0, abs=0.2)
        assert 18.0 <= io["supply_air_c"] <= 27.0, "inside the recommended envelope"
        assert io["thermally_critical"] is False
    for train in TRAINS:
        assert plant.module("cooling.eroom", train).io["room_c"] == pytest.approx(24.0, abs=0.3)
        assert plant.module("electrical.power_train", train).io["state"] == "ON_UTILITY"
