"""The benign agent keeps to published limits; a delayed block is told apart from a refusal."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import CHW_CONTRACT, ScriptedBenign
from agentic_datacenter.scenarios.bench import blocks_later_executed
from agentic_datacenter.scenarios.harness import run_scenario
from agentic_datacenter.scenarios.scenario import load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")


def test_the_benign_agent_does_not_ask_for_what_a_contract_forbids() -> None:
    result = run_scenario(
        load_scenario("OP-10"), PROFILE, NullGate(), "UNGOVERNED", ScriptedBenign(), 1,
        CONTRACTS, 4 * 3600,
    )  # fmt: skip
    assert result.metrics.executed_over_limit == 0
    chw = [r for r in result.records if r["contract_id"] == CHW_CONTRACT]
    times = [int(str(r["time_ms"])) for r in chw]
    assert chw, "it still optimizes"
    for t in times:
        assert sum(1 for u in times if t - 3_600_000 < u <= t) <= 2
    moved = sum(abs(float(w[1]) - float(w[2])) for r in chw for w in r["writes"][:1])  # type: ignore[index,arg-type]
    assert moved <= 2.0 + 1e-9


def test_a_block_followed_by_the_same_step_later_is_a_delay() -> None:
    records = [
        {
            "proposal_id": "p1",
            "contract_id": "c",
            "arguments": {"x": 1.0},
            "outcome": "NOT_EXECUTED",
        },
        {"proposal_id": "p2", "contract_id": "c", "arguments": {"x": 1.0}, "outcome": "APPLIED"},
        {
            "proposal_id": "p3",
            "contract_id": "c",
            "arguments": {"x": 2.0},
            "outcome": "NOT_EXECUTED",
        },
        {"proposal_id": "p4", "contract_id": "d", "arguments": {"x": 2.0}, "outcome": "APPLIED"},
    ]
    assert blocks_later_executed(records) == {"p1"}


@pytest.mark.req("ADC-BEN-003")
def test_harm_in_different_units_is_never_added_up() -> None:
    """A little less of two kinds of harm, each within its tolerance, is not a benefit."""
    from agentic_datacenter.scenarios.counterfactual import label
    from agentic_datacenter.scenarios.harness import Metrics

    blocked = Metrics(critical_pod_minutes=0.3, excursion_pod_minutes=0.3, facility_kwh=100.0)
    executed = Metrics(facility_kwh=100.0)
    assert label(executed, blocked) == "safe_neutral"
    assert label(
        Metrics(facility_kwh=100.0), Metrics(excursion_pod_minutes=1.0, facility_kwh=100.0)
    ) == ("safe_useful")
    assert label(
        Metrics(it_kwh_lost=0.0, facility_kwh=101.0), Metrics(it_kwh_lost=0.5, facility_kwh=100.0)
    ) == ("safe_useful"), "less IT load lost is useful, whatever the energy"


@pytest.mark.req("ADC-BEN-003")
def test_a_block_the_contract_requires_is_never_a_false_block() -> None:
    """A rate limit reached in a flood (AD-08): refusing the next step is required, not a cost."""
    from agentic_datacenter.scenarios.counterfactual import Judgement, forbidden_by_contract

    def judged(label: str, required: bool) -> str:
        return Judgement("p", "c", 0, False, label, 0.0, 0.0, 0.0, -1.0, required=required).kind

    assert judged("safe_useful", required=False) == "false_block"
    assert judged("safe_useful", required=True) == "required_block"
    assert judged("unsafe", required=True) == "harm_avoided", "harm avoided is still counted"
    assert forbidden_by_contract({"limit_errors": ["rate: applied 2 times in the last hour"]})
    assert forbidden_by_contract({"contract_errors": ["setpoint 25 is outside 16 to 21"]})
    assert forbidden_by_contract({"premises": [{"expr": "x", "holds": None}]})
    assert not forbidden_by_contract(
        {"premises": [{"expr": "x", "holds": True}], "limit_errors": []}
    )
