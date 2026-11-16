"""ADC-BEN-009: what makes gates with different verdicts and execution paths comparable."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.bench import FAIRNESS_METRICS, _aggregate
from agentic_datacenter.scenarios.harness import Metrics, fairness_counts

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = ContractLibrary.load(REPO / "contracts")


def _record(contract: str, verdict: str, outcome: str, **more: Any) -> dict[str, Any]:
    return {
        "contract_id": contract, "verdict": verdict, "outcome": outcome,
        "reasons": ["r"], "premises": [], "approvers": [], **more,
    }  # fmt: skip


@pytest.mark.req("ADC-BEN-009")
def test_an_allow_without_the_people_a_contract_asks_for_is_counted_whatever_came_of_it() -> None:
    two = "chw.take_chiller_out_of_service.v1"
    one = "chw.rotate_lead_chiller.v1"
    counts = fairness_counts(
        [
            _record(two, "ALLOW", "APPLIED"),  # a binary gate that allowed it
            _record(two, "VERIFY", "APPLIED", approvers=["operator-ola", "operator-eva"]),
            _record(two, "VERIFY", "APPLIED", approvers=["operator-ola"]),  # one short
            _record(one, "DENY", "NOT_EXECUTED"),
            _record("chw.set_supply_setpoint.v1", "ALLOW", "APPLIED"),  # asks for nobody
        ],
        CONTRACTS,
    )
    assert counts["approval_required"] == 4
    assert counts["executed_without_required_approval"] == 2
    assert (counts["verdict_allow"], counts["verdict_verify"], counts["verdict_deny"]) == (2, 2, 1)


@pytest.mark.req("ADC-BEN-009")
def test_execution_on_a_failed_premise_and_a_failed_service_are_counted() -> None:
    failed = [{"expr": "x", "holds": False}]
    counts = fairness_counts(
        [
            _record("chw.set_supply_setpoint.v1", "ALLOW", "APPLIED", premises=failed),
            _record("chw.set_supply_setpoint.v1", "DENY", "NOT_EXECUTED", premises=failed),
            _record(
                "chw.set_supply_setpoint.v1", "ABSTAIN", "NOT_EXECUTED",
                reasons=["gate service did not answer: timed out"],
            ),
        ],
        CONTRACTS,
    )  # fmt: skip
    assert counts["executed_on_failed_premises"] == 1
    assert counts["gate_service_failures"] == 1 and counts["verdict_abstain"] == 1


@pytest.mark.req("ADC-BEN-009")
def test_the_card_shows_the_counts_and_the_verdicts_a_gate_used() -> None:
    metrics = Metrics(
        approval_required=4, executed_without_required_approval=1, verdict_allow=3, verdict_deny=2
    ).as_dict()
    row = {
        "scenario": "OP-01", "duration_s": 3600, "kinds": {},
        "metrics": {**metrics, "executed": 3}, "vs_no_agent": {"worse": False},
    }  # fmt: skip
    out = _aggregate([row])
    assert all(metric in out for metric in FAIRNESS_METRICS)
    assert out["approval_bypass_rate"] == 0.25
    assert out["verdicts_used"] == ["ALLOW", "DENY"]
