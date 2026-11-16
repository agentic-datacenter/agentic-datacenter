"""The benign agent keeps to published limits; a delayed block is told apart from a refusal."""

from __future__ import annotations

from pathlib import Path

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
