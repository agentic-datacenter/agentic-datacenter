"""The branches of a what-if: same start, and a physical branch held without any agent or gate."""

from collections.abc import Callable
from typing import Any

import pytest

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.whatif.models import WhatIfSpec
from agentic_datacenter.whatif.runner import WhatIfResult, run_whatif

TANK = "cooling.tes[TES-1].supply_sp_c"
PLANT = "cooling.chw_plant[CHW].chws_sp_c"


@pytest.fixture(scope="module")
def result(profile: Profile, contracts: ContractLibrary) -> WhatIfResult:
    from agentic_datacenter.whatif.models import parse_spec

    spec = parse_spec({
        "scenario": "WF-01", "duration_s": 3600, "branches": ["baseline", "physical"],
        "change": {"contract_id": "chw.set_supply_setpoint.v1", "argument": "setpoint_c",
                   "target": 20.5, "expected_start": 18.0},
        "policy": {"enabled": False},
    })  # fmt: skip
    return run_whatif(spec, profile, contracts, gates={})


@pytest.mark.req("ADC-WIF-001")
def test_every_branch_starts_from_the_same_state_hash(result: WhatIfResult) -> None:
    hashes = result.start_state_hashes
    assert set(hashes) == {"baseline", "physical"}
    assert len(set(hashes.values())) == 1 and len(next(iter(hashes.values()))) == 64
    assert result.preflight["start_state_hash"] == hashes["baseline"]


@pytest.mark.req("ADC-WIF-001")
def test_the_physical_branch_holds_the_target_on_both_written_points(
    result: WhatIfResult,
) -> None:
    physical = result.branches["physical"]
    assert physical.hypothetical and "hypothetical" in physical.label.lower()
    assert physical.override is not None
    assert physical.override["tags"] == [PLANT, TANK]
    assert physical.override["value"] == 20.5
    assert physical.final_values == {PLANT: 20.5, TANK: 20.5}
    assert all(row["chws_sp_c"] == 20.5 for row in physical.series)
    baseline = result.branches["baseline"]
    assert all(row["chws_sp_c"] == 18.0 for row in baseline.series)


@pytest.mark.req("ADC-WIF-001")
def test_the_physical_branch_writes_nothing_through_the_command_service_and_asks_no_gate(
    result: WhatIfResult,
) -> None:
    physical = result.branches["physical"]
    assert physical.run is not None
    assert physical.run.change_log == [] and physical.run.records == []
    assert physical.operating_profile == "BASELINE_RULES" and physical.agent == "none"
    assert physical.governance is None, "a hypothetical branch has no governance verdict"


def test_series_are_kept_at_fifteen_minute_resolution(result: WhatIfResult) -> None:
    rows = result.branches["baseline"].series
    assert [row["t_s"] for row in rows] == [900, 1800, 2700, 3600]
    expected = {
        "t_s",
        "facility_kw",
        "it_kw",
        "chiller_kw",
        "pump_kw",
        "fan_kw",
        "hottest_pod_c",
        "chws_sp_c",
        "tes_charge_pct",
    }
    assert set(rows[0]) == expected


def test_energy_is_measured_per_branch_and_compared_against_the_baseline(
    result: WhatIfResult,
) -> None:
    for name in ("baseline", "physical"):
        energy = result.branches[name].energy
        for key in ("facility_kwh", "it_kwh", "pue", "chiller_kwh", "pump_kwh", "fan_kwh"):
            assert energy[key] > 0.0, (name, key)
        assert energy["model_estimate"] is True
    saving = result.comparison["physical"]
    baseline, physical = result.branches["baseline"].energy, result.branches["physical"].energy
    assert saving["facility_kwh_saved"] == pytest.approx(
        baseline["facility_kwh"] - physical["facility_kwh"]
    )
    assert saving["facility_saved_pct"] == pytest.approx(
        100.0 * saving["facility_kwh_saved"] / baseline["facility_kwh"]
    )
    assert physical["chiller_kwh"] < baseline["chiller_kwh"], "warmer water, less lift"
    assert saving["cost_saved"] is None, "no price was given, so no cost"


def test_a_governed_branch_without_its_gate_is_not_run_and_says_why(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    spec = make_spec(duration_s=900, branches=["baseline", "governed"])
    result = run_whatif(spec, profile, contracts, gates={})
    governed = result.branches["governed"]
    assert governed.available is False and "remora_governed" in str(governed.unavailable_reason)
    assert "governed" not in result.comparison


def test_the_summary_is_json_and_labels_the_policy_part_when_it_is_off(
    result: WhatIfResult,
) -> None:
    import json

    summary: dict[str, Any] = json.loads(json.dumps(result.summary()))
    assert summary["request"]["scenario"] == "WF-01"
    assert summary["policy"]["available"] is False
    assert summary["branches"]["physical"]["hypothetical"] is True
    assert "simulation" in " ".join(summary["statements"]).lower()
