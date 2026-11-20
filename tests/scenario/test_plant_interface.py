"""The built-in plant behind the plant interface, and a harness that reaches it so (ADR 0029)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from agentic_datacenter.core.module import ModuleContractError
from agentic_datacenter.core.plant_interface import HARM_CHANNELS, PlantModel
from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.scenarios.plant import BuiltinPlant

REPO = Path(__file__).resolve().parents[2]
SCENARIOS = REPO / "packages/agentic-datacenter-scenarios/src/agentic_datacenter/scenarios"
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")


@pytest.fixture(scope="module")
def plant() -> BuiltinPlant:
    return BuiltinPlant(PROFILE, Kernel(seed=1))


@pytest.mark.req("ADC-PLT-001")
def test_the_built_in_plant_is_a_plant_model(plant: BuiltinPlant) -> None:
    assert isinstance(plant, PlantModel)


@pytest.mark.req("ADC-PLT-001")
def test_it_describes_its_points_faults_relays_and_harm_channels(plant: BuiltinPlant) -> None:
    described = plant.describe()
    assert described.step_ms == 100 and described.offers_capture
    assert described.harm_channels == HARM_CHANNELS
    tags = {p.tag: p for p in described.points}
    setpoint = tags["cooling.chw_plant[CHW].chws_sp_c"]
    assert setpoint.tier in ("T2", "T3") and setpoint.unit and setpoint.zone.startswith("Z")
    assert "cooling.pod[01]" in described.faults and "reboot" in described.faults["cooling.pod[01]"]
    owner, zone = described.relays["IED-FDR-A"]
    assert owner.startswith("electrical.mv_switchgear[") and zone.startswith("Z")


@pytest.mark.req("ADC-PLT-001")
def test_harm_is_read_from_the_true_state_of_every_space_and_load(plant: BuiltinPlant) -> None:
    harm = plant.harm()
    pods = [p for p in plant.describe().faults if p.startswith("cooling.pod[")]
    assert len(harm.supply_air_c) == len(pods) > 0
    assert all(v == 0.0 for v in harm.it_kwh_lost) and len(harm.it_served_kw) > 0
    assert harm.facility_in_kw and harm.both_closed


@pytest.mark.req("ADC-PLT-001")
def test_a_write_returns_what_it_replaced_and_an_unknown_target_is_refused(
    plant: BuiltinPlant,
) -> None:
    tag = "cooling.chw_plant[CHW].chws_sp_c"
    old = plant.write(tag, 19.0)
    assert plant.write(tag, old) == 19.0
    with pytest.raises(ModuleContractError):
        plant.inject("cooling.nothing[X]", "fail", {})


@pytest.mark.req("ADC-PLT-001")
@pytest.mark.parametrize("source", ["harness.py", "counterfactual.py"])
def test_the_harness_and_the_oracle_reach_the_plant_only_through_the_interface(
    source: str,
) -> None:
    text = (SCENARIOS / source).read_text(encoding="utf-8")
    for pattern in (
        r"\.instances\(\)", r"manifest\.id", r"\bbuild_plant\b", r"\.plant\.module\(",
        r"module\.ts\b", r"module\.io\b", r"power_balance", r"relay_tags",
    ):  # fmt: skip
        assert not re.search(pattern, text), f"{source} reaches the plant itself: {pattern}"
