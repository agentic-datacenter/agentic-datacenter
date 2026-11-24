"""The number of chillers is a parameter of the plant (ADR 0033, decision 7)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from agentic_datacenter.core.profile import build_plant, load_profile, parse_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.plant.cooling.chw_plant.unit import POINTS, plant_points
from agentic_datacenter.scenarios.facility_fit import fit_facility
from agentic_datacenter.supervisory.overview import Overview
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[2]
GENERIC = REPO / "profiles/generic_dc.yaml"


def with_chillers(count: float) -> Any:
    data: dict[str, Any] = yaml.safe_load(GENERIC.read_text(encoding="utf-8"))
    use = next(u for u in data["modules"] if u["id"] == "cooling.chw_plant")
    use["params"]["chillers"] = {"value": count, "unit": "-", "assumed": True}
    return parse_profile(data)


def built(profile: Any) -> tuple[Kernel, Any, PointDatabase]:
    kernel = Kernel(seed=1)
    plant = build_plant(profile, kernel, ModuleRegistry.from_entry_points())
    return kernel, plant, PointDatabase(kernel, plant)


@pytest.mark.req("ADC-FAC-010")
def test_three_chillers_are_the_points_of_the_plant_as_they_were() -> None:
    assert plant_points(3) == POINTS
    _, plant, _ = built(load_profile(GENERIC))
    assert plant.module("cooling.chw_plant", "CHW").chillers == (1, 2, 3)


@pytest.mark.req("ADC-FAC-010")
def test_a_fourth_chiller_has_its_points_shares_the_first_feed_and_counts() -> None:
    kernel, plant, points = built(with_chillers(4))
    module = plant.module("cooling.chw_plant", "CHW")
    tags = set(points.tags())
    assert {"cooling.chw_plant[CHW].ch4_state", "cooling.chw_plant[CHW].ch4_enable"} <= tags
    assert points.declaration("cooling.chw_plant[CHW].lead_chiller").values == ("1", "2", "3", "4")
    assert module.feed_of[4] == 1
    kernel.run_for(5_000)
    assert Overview(points).redundancy()["chillers"].available == 4
    module.inject("chiller_trip", chiller=1)
    module.inject("chiller_trip", chiller=2)
    kernel.run_for(600_000)
    states = {n: points.read(f"cooling.chw_plant[CHW].ch{n}_state").value for n in (3, 4)}
    assert states == {3: "RUNNING", 4: "RUNNING"}


@pytest.mark.req("ADC-FAC-010")
def test_two_chillers_have_no_points_of_a_third_and_its_contracts_do_not_fit() -> None:
    profile = with_chillers(2)
    _, _, points = built(profile)
    assert "cooling.chw_plant[CHW].ch3_state" not in set(points.tags())
    fit = fit_facility(profile, ContractLibrary.load(REPO / "contracts"), ["OP-03"])
    assert "chw.take_chiller_out_of_service.v1" in fit.not_loaded
    assert "ch3_enable" in fit.not_loaded["chw.take_chiller_out_of_service.v1"]


@pytest.mark.req("ADC-FAC-010")
def test_a_count_outside_one_to_nine_is_refused() -> None:
    with pytest.raises(ValueError, match="1 to 9"):
        built(with_chillers(10))


@pytest.mark.req("ADC-FAC-010")
def test_a_whole_number_given_as_a_float_is_taken_and_a_fraction_is_refused() -> None:
    """From the review of PR 44: 4.0 crashed the fit check, and 2.7 became 2 without a word."""
    fit = fit_facility(with_chillers(4.0), ContractLibrary.load(REPO / "contracts"), ["OP-03"])
    assert fit.runnable == ["OP-03"]
    with pytest.raises(ValueError, match="whole number"):
        built(with_chillers(2.7))
