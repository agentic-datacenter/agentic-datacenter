"""ADC-BEN-008: a bounded counterfactual replay, and what it is checked against."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.static_allowlist import create as static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios import counterfactual
from agentic_datacenter.scenarios.agents import ScriptedAdversarial
from agentic_datacenter.scenarios.bench import TIERS
from agentic_datacenter.scenarios.counterfactual import judge_run
from agentic_datacenter.scenarios.harness import ScenarioRun
from agentic_datacenter.scenarios.scenario import load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")


def _judge(horizon_s: int | None, max_judged: int | None = None):  # type: ignore[no-untyped-def]
    return judge_run(
        load_scenario("AD-03"), PROFILE, static_allowlist, "STATIC_ALLOWLIST",
        ScriptedAdversarial, 1, CONTRACTS, 1800, horizon_s=horizon_s, max_judged=max_judged,
    )  # fmt: skip


@pytest.mark.req("ADC-BEN-008")
def test_a_horizon_that_reaches_the_end_judges_as_an_unbounded_replay() -> None:
    unbounded_result, unbounded = _judge(None)
    bounded_result, bounded = _judge(1800)
    assert unbounded and bounded == unbounded
    assert unbounded_result.judging["judged"] == unbounded_result.judging["candidates"]
    assert bounded_result.judging["horizon_s"] == 1800


@pytest.mark.req("ADC-BEN-008")
def test_a_short_horizon_judges_every_proposal_on_the_same_instants() -> None:
    result, judged = _judge(300)
    assert len(judged) == result.judging["candidates"] == result.judging["judged"]
    assert all(j.kind for j in judged)


@pytest.mark.req("ADC-BEN-008")
def test_the_judged_sample_is_fixed_by_scenario_seed_and_proposal() -> None:
    _, everything = _judge(300)
    result, sample = _judge(300, max_judged=3)
    again = _judge(300, max_judged=3)[1]
    assert len(sample) == 3 and sample == again
    assert {j.proposal_id for j in sample} <= {j.proposal_id for j in everything}
    assert result.judging == {
        "horizon_s": 300, "max_judged": 3, "candidates": len(everything), "judged": 3,
        "branches_from": "capture",
    }  # fmt: skip


class _Watched(ScenarioRun):
    """A run that counts the captures it takes, and is listed when it is built."""

    built: ClassVar[list[_Watched]] = []

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.captured_at: list[int] = []
        self.built.append(self)

    def capture(self) -> dict[str, Any]:
        self.captured_at.append(self.second)
        return super().capture()


def _keeps_state(contracts: ContractLibrary) -> Any:
    """The allowlist, declared as a gate whose state a capture cannot hold."""
    gate: Any = static_allowlist(contracts)
    gate.restorable, gate.snapshots_taken = False, 0

    def snapshot_state() -> dict[str, Any]:
        gate.snapshots_taken += 1
        return {"outcomes": dict(gate.outcomes)}

    def restore_state(state: dict[str, Any]) -> None:
        gate.outcomes = dict(state["outcomes"])

    gate.snapshot_state, gate.restore_state = snapshot_state, restore_state
    return gate


@pytest.fixture
def watched(monkeypatch: pytest.MonkeyPatch) -> list[_Watched]:
    monkeypatch.setattr(counterfactual, "ScenarioRun", _Watched)
    monkeypatch.setattr(_Watched, "built", [])
    return _Watched.built


@pytest.mark.req("ADC-BEN-008")
def test_a_gate_that_keeps_state_is_captured_only_at_the_instants_judged(
    watched: list[_Watched],
) -> None:
    """A capture holds every record so far: a long run must not keep one per decision point."""
    result, sample = judge_run(
        load_scenario("AD-03"), PROFILE, _keeps_state, "STATIC_ALLOWLIST",
        ScriptedAdversarial, 1, CONTRACTS, 1800, horizon_s=300, max_judged=3,
    )  # fmt: skip
    assert result.judging["branches_from"] == "gate snapshot"
    assert result.judging["candidates"] > 3 and len(sample) == 3
    assert sample == _judge(300, max_judged=3)[1], "the same judgements as from captures"
    actual, source, *branches = watched[:5]
    instants = sorted({j.time_ms // 1000 - load_scenario("AD-03").warmup_s for j in sample})
    assert len(actual.decision_points) > len(instants)
    assert actual.captured_at == [], "nothing is restored from the first run"
    assert source.captured_at == instants
    assert source.gate.snapshots_taken == len(instants)
    assert not source.captures and not source.gate_snapshots, "released when last used"
    assert len(branches) == 3 and all(b.captured_at == [] for b in branches)


@pytest.mark.req("ADC-BEN-008")
def test_captures_are_released_once_their_branches_are_judged(watched: list[_Watched]) -> None:
    result, sample = _judge(300, max_judged=3)
    actual = watched[0]
    assert result.judging["branches_from"] == "capture" and len(sample) == 3
    assert actual.captured_at == sorted(actual.decision_points), "chosen after the run"
    assert not actual.captures


def test_the_tiers_are_bounded_except_the_reference() -> None:
    assert TIERS["full"]["horizon_s"] is None and TIERS["full"]["max_judged"] is None
    assert TIERS["standard"]["seconds"] is None and TIERS["standard"]["seeds"] == 3


@pytest.mark.req("ADC-BEN-008")
def test_a_scenario_can_ask_for_a_longer_replay_and_a_smaller_sample() -> None:
    week = load_scenario("OP-10")
    assert week.judging(3600, 64) == (86400, 16)
    assert week.judging(None, None) == (None, None), "the reference tier stays unbounded"
    assert load_scenario("AD-03").judging(3600, 64) == (3600, 64)
