"""The goal-seeking agent of the governed branch keeps to the contract's published limits."""

from collections.abc import Callable
from typing import Any

import pytest

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.whatif.agent import GoalSeekingAgent
from agentic_datacenter.whatif.models import WhatIfSpec
from agentic_datacenter.whatif.runner import run_whatif

HOUR_MS = 3_600_000


def applied(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [r for r in records if r["outcome"] in ("APPLIED", "ROLLED_BACK")]


@pytest.mark.req("ADC-WIF-002")
def test_it_stops_at_the_cumulative_limit_and_never_runs_past_the_rate(
    make_spec: Callable[..., WhatIfSpec],
    profile: Profile,
    contracts: ContractLibrary,
    stand_in_gates: dict[str, Any],
) -> None:
    spec = make_spec(20.5, duration_s=4 * 3600, branches=["baseline", "governed"])
    result = run_whatif(spec, profile, contracts, gates=stand_in_gates)
    governed = result.branches["governed"]
    assert governed.gate == "null_gate", "the stand-in is named, never passed off as REMORA"
    assert governed.run is not None
    done = applied(governed.run.records)
    times = [int(str(r["time_ms"])) for r in done]
    for t in times:
        assert sum(1 for u in times if t - HOUR_MS < u <= t) <= 2
    moved = sum(abs(float(w[1]) - float(w[2])) for r in done for w in r["writes"][:1])
    assert moved <= 2.0 + 1e-9
    assert all(abs(float(w[1]) - float(w[2])) <= 0.5 + 1e-9 for r in done for w in r["writes"])
    outcome = governed.outcome
    assert outcome is not None
    assert outcome["final_value"] == pytest.approx(20.0) and outcome["reached"] is False
    assert any("cumulative" in reason for reason in outcome["stopped_because"])
    assert result.start_state_hashes["governed"] == result.start_state_hashes["baseline"]


@pytest.mark.req("ADC-WIF-002")
def test_it_reaches_a_target_the_day_allows_and_then_proposes_nothing_more(
    make_spec: Callable[..., WhatIfSpec],
    profile: Profile,
    contracts: ContractLibrary,
    stand_in_gates: dict[str, Any],
) -> None:
    spec = make_spec(19.5, duration_s=3 * 3600, branches=["baseline", "governed"])
    result = run_whatif(spec, profile, contracts, gates=stand_in_gates)
    governed = result.branches["governed"]
    assert governed.run is not None and governed.outcome is not None
    assert len(applied(governed.run.records)) == 3
    assert len(governed.run.records) == 3, "no proposal after the target was reached"
    assert governed.outcome["reached"] is True and governed.outcome["final_value"] == 19.5
    assert governed.outcome["stopped_because"] == ["target reached"]


def test_its_log_says_why_it_held_back_at_each_decision_point(
    make_spec: Callable[..., WhatIfSpec],
    profile: Profile,
    contracts: ContractLibrary,
    stand_in_gates: dict[str, Any],
) -> None:
    spec = make_spec(20.5, duration_s=2 * 3600, branches=["baseline", "governed"])
    result = run_whatif(spec, profile, contracts, gates=stand_in_gates)
    log = result.branches["governed"].agent_log
    assert [entry["t_s"] for entry in log] == [900 * n for n in range(1, 8)]
    assert log[0]["action"] == "proposed" and log[0]["value"] == 18.5
    assert log[0]["verdict"] == "ALLOW" and log[0]["outcome"] == "APPLIED"
    assert log[2]["action"] == "held back" and "rate" in log[2]["reason"]


def test_the_agent_is_deterministic_and_restorable() -> None:
    agent = GoalSeekingAgent("chw.set_supply_setpoint.v1", "setpoint_c", 20.5)
    state = agent.snapshot()
    other = GoalSeekingAgent("chw.set_supply_setpoint.v1", "setpoint_c", 20.5)
    other.restore(state)
    assert other.snapshot() == state
    assert agent.name == "goal_seeking"
