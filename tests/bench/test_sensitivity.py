"""ADC-FID-004: conclusions are marked robust or not robust over the uncertain parameters."""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.scenarios.sensitivity import Variation, run_sensitivity

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
PODS = [f"{n:02d}" for n in range(1, 17)]

# The most uncertain assumed parameters named in SDD 6.7 and 14.
VARIATIONS = [
    Variation(
        "POD thermal capacity", "cooling.pod", "thermal_mass_kj_per_k", [3000.0, 4500.0, 6000.0]
    ),
    Variation(
        "Chiller restart lockout", "cooling.chw_plant", "restart_lockout_s", [120.0, 180.0, 300.0]
    ),
    Variation("UPS autonomy", "electrical.ups", "autonomy_s", [180.0, 300.0, 600.0]),
    Variation("Valve stroke time", "cooling.pod", "valve_stroke_s", [30.0, 60.0, 120.0]),
]


def chilled_water_lost(kernel: Kernel, plant: Any) -> dict[str, bool]:
    """All pumps fail at ten minutes; what is true four and eight minutes later?"""
    kernel.run_for(600_000)
    for pump in (1, 2, 3):
        plant.module("cooling.pump_station", "PHPS").inject("pump_fail", pump=pump)
    pods = [plant.module("cooling.pod", p) for p in PODS]
    kernel.run_for(240_000)
    survives_four_minutes = max(float(p.io["supply_air_c"]) for p in pods) < 32.0
    kernel.run_for(240_000)
    return {
        "A POD stays below 32 degC for four minutes without chilled water": survives_four_minutes,
        "Every POD is thermally critical eight minutes after chilled water is lost": all(
            p.io["thermally_critical"] for p in pods
        ),
        "No IT load is dropped when chilled water is lost": all(
            plant.module("electrical.it_load", p).io["kwh_lost"] == 0.0 for p in PODS
        ),
    }


@pytest.mark.req("ADC-FID-004")
def test_each_conclusion_is_marked_robust_or_not_over_the_uncertain_parameters() -> None:
    report = run_sensitivity(PROFILE, chilled_water_lost, VARIATIONS, seed=1)
    verdicts = {c.conclusion: c for c in report.conclusions}
    assert len(report.runs) == 1 + sum(len(v.values) for v in VARIATIONS)

    dropped = verdicts["No IT load is dropped when chilled water is lost"]
    # With the least thermal capacity the inlet passes the servers' shutdown
    # temperature within the eight minutes, and the load trips.
    assert dropped.baseline is True and dropped.robust is False
    flips = [(f.variation, f.value) for f in dropped.flipped_by]
    assert flips == [("POD thermal capacity", 3000.0)]

    critical = verdicts["Every POD is thermally critical eight minutes after chilled water is lost"]
    assert critical.baseline is True and critical.robust is True

    survives = verdicts["A POD stays below 32 degC for four minutes without chilled water"]
    assert survives.robust is False, "this one depends on the calibrated thermal capacity"
    assert [f.variation for f in survives.flipped_by] == ["POD thermal capacity"]
    assert "not robust" in report.to_markdown()
    assert "POD thermal capacity" in report.to_markdown()


@pytest.mark.req("ADC-FID-004")
def test_a_variation_that_names_an_unknown_module_or_parameter_is_refused() -> None:
    with pytest.raises(ValueError, match="no.such"):
        run_sensitivity(
            PROFILE, chilled_water_lost, [Variation("x", "no.such", "p", [1.0])], seed=1
        )


@pytest.mark.req("ADC-FID-002")
def test_no_module_claims_reference_checked_fidelity_without_a_committed_comparison_suite() -> None:
    from agentic_datacenter.core.registry import ModuleRegistry

    for manifest in ModuleRegistry.from_entry_points().manifests():
        if manifest.fidelity in ("F2", "F3"):
            suite = REPO / "tests/fidelity" / manifest.id
            assert (suite / "SOURCE.md").is_file(), f"{manifest.id} claims {manifest.fidelity}"
            assert list(suite.glob("test_*.py")), f"{manifest.id} has no comparison test"
