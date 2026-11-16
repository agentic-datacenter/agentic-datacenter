"""ADC-BEN-008: a bounded counterfactual replay, and what it is checked against."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.static_allowlist import create as static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import ScriptedAdversarial
from agentic_datacenter.scenarios.bench import TIERS
from agentic_datacenter.scenarios.counterfactual import judge_run
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


def test_the_tiers_are_bounded_except_the_reference() -> None:
    assert TIERS["full"]["horizon_s"] is None and TIERS["full"]["max_judged"] is None
    assert TIERS["standard"]["seconds"] is None and TIERS["standard"]["seeds"] == 3


@pytest.mark.req("ADC-BEN-008")
def test_a_scenario_can_ask_for_a_longer_replay_and_a_smaller_sample() -> None:
    week = load_scenario("OP-10")
    assert week.judging(3600, 64) == (86400, 16)
    assert week.judging(None, None) == (None, None), "the reference tier stays unbounded"
    assert load_scenario("AD-03").judging(3600, 64) == (3600, 64)
