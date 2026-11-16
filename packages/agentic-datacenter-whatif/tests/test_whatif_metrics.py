"""Physical and governance violations are reported apart (ADC-WIF-003)."""

from collections.abc import Callable
from typing import Any

import pytest

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.harness import Metrics
from agentic_datacenter.whatif.compare import compare
from agentic_datacenter.whatif.metrics import PHYSICAL, governance_violations, physical_violations
from agentic_datacenter.whatif.models import EnergyPrice, WhatIfSpec
from agentic_datacenter.whatif.runner import run_whatif

GOVERNANCE = ("executed_over_limit", "executed_on_stale_premises", "replays_accepted",
              "writes_outside_contract")  # fmt: skip


@pytest.mark.req("ADC-WIF-003")
def test_the_two_kinds_have_no_field_in_common() -> None:
    metrics = Metrics(critical_pod_minutes=3.0, executed_over_limit=1, replays_accepted=2)
    physical = physical_violations(metrics, min_tes_charge_pct=97.5, max_pod_c=24.1)
    governance = governance_violations(metrics)
    assert set(physical) == set(PHYSICAL)
    assert set(governance) == set(GOVERNANCE)
    assert not set(physical) & set(governance)
    assert physical["critical_pod_minutes"] == 3.0 and physical["max_pod_c"] == 24.1
    assert physical["min_tes_charge_pct"] == 97.5
    assert governance["executed_over_limit"] == 1 and governance["replays_accepted"] == 2


@pytest.mark.req("ADC-WIF-003")
def test_a_hypothetical_branch_is_never_counted_as_a_governance_failure(
    make_spec: Callable[..., WhatIfSpec],
    profile: Profile,
    contracts: ContractLibrary,
    stand_in_gates: dict[str, Any],
) -> None:
    spec = make_spec(20.5, duration_s=1800, branches=["baseline", "physical", "governed"])
    result = run_whatif(spec, profile, contracts, gates=stand_in_gates)
    summary = result.summary()
    physical = summary["branches"]["physical"]
    assert physical["governance"] == {
        "applicable": False,
        "reason": physical["governance"]["reason"],
    }
    assert "hypothetical" in physical["governance"]["reason"]
    assert set(physical["physical"]) == set(PHYSICAL)
    governed = summary["branches"]["governed"]
    assert governed["governance"]["applicable"] is True
    assert set(governed["governance"]["violations"]) == set(GOVERNANCE)
    totals = summary["violations"]
    assert set(totals) == {"physical", "governance"}
    assert "physical" not in totals["governance"]["by_branch"]


def test_cost_is_only_kwh_times_the_given_price() -> None:
    base = {"facility_kwh": 1000.0, "chiller_kwh": 300.0, "pump_kwh": 50.0, "fan_kwh": 80.0,
            "it_kwh": 800.0, "pue": 1.25}  # fmt: skip
    cand = {**base, "facility_kwh": 960.0, "chiller_kwh": 262.0, "pue": 1.2}
    out = compare(base, cand, EnergyPrice(per_kwh=1.5, currency="NOK"))
    assert out["facility_kwh_saved"] == pytest.approx(40.0)
    assert out["facility_saved_pct"] == pytest.approx(4.0)
    assert out["chiller_kwh_saved"] == pytest.approx(38.0)
    assert out["cost_saved"] == pytest.approx(60.0) and out["currency"] == "NOK"
    assert "annual" not in repr(out)
    assert compare(base, cand, None)["cost_saved"] is None
