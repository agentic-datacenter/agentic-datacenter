"""ADC-BEN-003: counterfactual replay restores the exact state and reproduces the run."""

from pathlib import Path

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.null_gate import create as null_gate
from agentic_datacenter.governance.bindings.static_allowlist import create as static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import ScriptedAdversarial, ScriptedBenign
from agentic_datacenter.scenarios.counterfactual import judge_run, replay_unchanged
from agentic_datacenter.scenarios.scenario import load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")


@pytest.mark.req("ADC-BEN-003")
@pytest.mark.parametrize(
    ("make_gate", "profile"), [(null_gate, "UNGOVERNED"), (static_allowlist, "STATIC_ALLOWLIST")]
)
def test_replaying_the_decision_that_was_taken_reproduces_the_original_run(
    make_gate: object, profile: str
) -> None:
    original, replayed, at_capture, restored = replay_unchanged(
        load_scenario("AD-03"),
        PROFILE,
        make_gate,
        profile,
        ScriptedAdversarial,
        1,
        CONTRACTS,  # type: ignore[arg-type]
        duration_s=2400,
        from_second=1200,
    )
    assert restored == at_capture, "the restored state is the pre-decision state, exactly"
    assert replayed.state_hashes == original.state_hashes
    assert replayed.metrics == original.metrics
    assert replayed.records == original.records


@pytest.mark.req("ADC-KRN-001")
def test_no_part_of_the_state_changes_without_the_state_hash_seeing_it() -> None:
    """Every tracked part must say when it changes, or a hash would hide a difference."""
    from agentic_datacenter.scenarios.harness import ScenarioRun

    run = ScenarioRun(
        load_scenario("AD-01"),
        PROFILE,
        static_allowlist,
        "STATIC_ALLOWLIST",
        ScriptedAdversarial,
        1,
        CONTRACTS,
        duration_s=2400,
    )
    run.run()
    run.world.points.set_link(False)
    run.world.kernel.run_for(10_000)
    run.world.kernel.state_hash()
    run.world.kernel.run_for(10_000)
    assert run.world.kernel.state.stale_parts() == []


@pytest.mark.nightly
@pytest.mark.req("ADC-BEN-003")
def test_blocked_unsafe_proposal_is_harm_avoided_and_blocked_useful_one_is_a_false_block() -> None:
    """A gate that blocks everything avoids the harm and blocks the benefit: both are counted."""
    from agentic_datacenter.governance.bindings.static_allowlist import StaticAllowlist

    def nothing_allowed(_: ContractLibrary) -> StaticAllowlist:
        return StaticAllowlist([])

    scenario = load_scenario("OP-10")
    _, careful = judge_run(
        scenario,
        PROFILE,
        nothing_allowed,
        "STATIC_ALLOWLIST",  # type: ignore[arg-type]
        ScriptedBenign,
        1,
        CONTRACTS,
        duration_s=3600,
    )
    kinds = [j.kind for j in careful]
    assert kinds and set(kinds) <= {"false_block", "blocked_neutral"}
    assert "false_block" in kinds, "a setpoint raise on a healthy plant would have saved energy"
    assert all(j.delta_facility_kwh < 0 for j in careful if j.kind == "false_block")

    _, hostile = judge_run(
        load_scenario("OP-03"),
        PROFILE,
        nothing_allowed,
        "STATIC_ALLOWLIST",  # type: ignore[arg-type]
        ScriptedAdversarial,
        1,
        CONTRACTS,
        duration_s=3600,
    )
    by_kind = {j.kind for j in hostile}
    assert "not_executable" in by_kind, "an unknown contract cannot be executed by anyone"
    assert "harm_avoided" in by_kind, "blocking the unsafe proposals avoided measurable harm"


@pytest.mark.nightly
@pytest.mark.req("ADC-BEN-003")
def test_executed_unsafe_proposal_is_counted_as_an_unsafe_execution() -> None:
    _, judged = judge_run(
        load_scenario("OP-03"),
        PROFILE,
        null_gate,
        "UNGOVERNED",  # type: ignore[arg-type]
        ScriptedAdversarial,
        1,
        CONTRACTS,
        duration_s=3600,
    )
    kinds = {j.kind for j in judged}
    assert "unsafe_execution" in kinds
    worst = max(judged, key=lambda j: j.delta_critical_pod_minutes + j.delta_excursion_pod_minutes)
    assert worst.executed and worst.label == "unsafe"
