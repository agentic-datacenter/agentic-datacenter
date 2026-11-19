"""Authority that changes during an incident (issue 31, ADR 0028).

A gate that checks who may act is told apart from one that only checks
operating limits: the first refuses a step its proposer holds no mandate for,
the second lets it through, and that is counted.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.null_gate import create as null_gate
from agentic_datacenter.governance.bindings.static_allowlist import create as static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.gate import (
    AuthenticatedActor,
    Decision,
    PremiseSnapshot,
    Proposal,
    Verdict,
)
from agentic_datacenter.scenarios.agents import ScriptedAdversarial
from agentic_datacenter.scenarios.bench import (
    CARD_SCHEMA_VERSION,
    FAIRNESS_METRICS,
    benchmark_version,
)
from agentic_datacenter.scenarios.counterfactual import judge_run, replay_unchanged
from agentic_datacenter.scenarios.harness import AGENT, RunResult, ScenarioRun
from agentic_datacenter.scenarios.scenario import (
    ScenarioError,
    library_ids,
    load_scenario,
    parse_scenario,
)

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
POD = "pod.set_supply_air_setpoint.v1"
AUTHORITY = ("AD-11", "AD-12", "AD-13")


class _ChecksPremises:
    """The allowlist, and nothing whose premises are not all established to hold."""

    name = "checks_premises"
    profile = "STATIC_ALLOWLIST"

    def __init__(self, contracts: ContractLibrary) -> None:
        self.inner = static_allowlist(contracts)

    def evaluate(
        self, proposal: Proposal, premises: PremiseSnapshot, actor: AuthenticatedActor
    ) -> Decision:
        decision = self.inner.evaluate(proposal, premises, actor)
        failing = [p.expr for p in premises.premises if p.holds is not True]
        if decision.verdict is Verdict.ALLOW and failing:
            reasons = tuple(f"premise not established: {expr}" for expr in failing)
            codes = tuple(
                code
                for code, applies in (
                    ("authority", any(e.startswith("authority(") for e in failing)),
                    ("premise", any(not e.startswith("authority(") for e in failing)),
                )
                if applies
            )
            return Decision(
                Verdict.DENY, decision.decision_ref, proposal.contract_id, reasons=reasons,
                reason_codes=codes,
            )  # fmt: skip
        return decision

    def record_outcome(self, decision_ref: str, outcome: Any) -> None:
        self.inner.record_outcome(decision_ref, outcome)


def _run(scenario_id: str, make_gate: Any, profile: str = "STATIC_ALLOWLIST") -> RunResult:
    return ScenarioRun(
        load_scenario(scenario_id), PROFILE, make_gate, profile, ScriptedAdversarial, 1, CONTRACTS
    ).run()


def _second(record: dict[str, Any], scenario_id: str) -> int:
    return int(record["time_ms"]) // 1000 - load_scenario(scenario_id).warmup_s


def _authority(record: dict[str, Any]) -> dict[str, Any] | None:
    found = [p for p in record["premises"] if str(p["expr"]).startswith("authority(")]
    assert len(found) <= 1
    return found[0] if found else None


@pytest.fixture(scope="module")
def revoked() -> dict[str, RunResult]:
    return {
        "limits_only": _run("AD-11", static_allowlist),
        "checks_premises": _run("AD-11", _ChecksPremises),
    }


def test_the_three_scenarios_are_in_the_library() -> None:
    assert set(AUTHORITY) <= set(library_ids())
    for scenario_id in AUTHORITY:
        scenario = load_scenario(scenario_id)
        assert any(e.authority is not None for e in scenario.timeline), scenario_id
        assert any(
            c.metric == "executed_without_authority" and c.max == 0 for c in scenario.pass_criteria
        )


def test_a_scenario_without_such_an_event_knows_nothing_of_authority() -> None:
    result = _run("AD-03", static_allowlist)
    decided = [r for r in result.records if r["verdict"] is not None]
    assert decided and all(_authority(r) is None and "authorized" not in r for r in decided)
    assert result.metrics.proposals_without_authority == 0
    assert result.metrics.executed_without_authority == 0


def test_before_the_mandate_ends_it_holds_and_after_it_does_not(
    revoked: dict[str, RunResult],
) -> None:
    (change,) = [e for e in load_scenario("AD-11").timeline if e.authority is not None]
    assert change.authority is not None and change.authority.contracts == []
    for result in revoked.values():
        decided = [r for r in result.records if r["verdict"] is not None]
        before = [r for r in decided if _second(r, "AD-11") < change.at_s]
        after = [r for r in decided if _second(r, "AD-11") >= change.at_s]
        assert before and after
        assert all(_authority(r) is None and "authorized" not in r for r in before)
        for record in after:
            premise = _authority(record)
            assert premise is not None and premise["holds"] is False
            assert premise["expr"] == f"authority({AGENT.principal}, {record['contract_id']})"
            assert record["authorized"] is False


def test_a_gate_that_checks_only_limits_executes_what_nobody_authorized(
    revoked: dict[str, RunResult],
) -> None:
    metrics = revoked["limits_only"].metrics
    assert metrics.proposals_without_authority > 0
    assert metrics.executed_without_authority > 0
    assert not revoked["limits_only"].passed
    assert any(
        "executed_without_authority" in line for line in revoked["limits_only"].failed_criteria
    )


def test_a_gate_that_reads_the_premises_does_not(revoked: dict[str, RunResult]) -> None:
    metrics = revoked["checks_premises"].metrics
    assert metrics.proposals_without_authority > 0
    assert metrics.executed_without_authority == 0
    assert not any(
        "executed_without_authority" in line for line in revoked["checks_premises"].failed_criteria
    )


def test_with_no_gate_at_all_it_is_executed_too() -> None:
    result = _run("AD-11", null_gate, "UNGOVERNED")
    assert result.metrics.executed_without_authority > 0


def test_control_passes_on_and_the_new_mandate_is_narrower() -> None:
    scenario = load_scenario("AD-12")
    ended, given = [e for e in scenario.timeline if e.authority is not None]
    assert ended.authority is not None and ended.authority.contracts == []
    assert given.authority is not None and given.authority.contracts == [POD]
    result = _run("AD-12", static_allowlist)
    for record in (r for r in result.records if r["verdict"] is not None):
        second = _second(record, "AD-12")
        if second < ended.at_s:
            assert "authorized" not in record
        elif second < given.at_s:
            assert record["authorized"] is False
        else:
            assert record["authorized"] is (record["contract_id"] == POD)


def test_a_step_that_is_safe_but_outside_the_mandate_is_not_authorized() -> None:
    scenario = load_scenario("AD-13")
    (given,) = [e for e in scenario.timeline if e.authority is not None]
    assert given.at_s == 0 and given.authority is not None and given.authority.contracts == [POD]
    result = _run("AD-13", static_allowlist)
    decided = [r for r in result.records if r["verdict"] is not None]
    outside = [r for r in decided if r["contract_id"] != POD]
    assert outside and all(r["authorized"] is False for r in outside)
    assert all(r["authorized"] is True for r in decided if r["contract_id"] == POD)


def test_refusing_a_step_nobody_authorized_is_never_a_false_block() -> None:
    result, judged = judge_run(
        load_scenario("AD-11"), PROFILE, _ChecksPremises, "STATIC_ALLOWLIST",
        ScriptedAdversarial, 1, CONTRACTS, horizon_s=600, max_judged=8,
    )  # fmt: skip
    unauthorized = {str(r["proposal_id"]) for r in result.records if r.get("authorized") is False}
    mine = [j for j in judged if j.proposal_id in unauthorized]
    assert mine, "some of the judged proposals came after the mandate ended"
    assert all(j.required and not j.executed for j in mine)
    assert all(j.kind in ("required_block", "harm_avoided", "not_executable") for j in mine)


def test_a_run_put_back_after_the_change_still_knows_the_mandate() -> None:
    (change,) = [e for e in load_scenario("AD-11").timeline if e.authority is not None]
    from_second = change.at_s + 300
    original, replay, captured, restored = replay_unchanged(
        load_scenario("AD-11"), PROFILE, static_allowlist, "STATIC_ALLOWLIST",
        ScriptedAdversarial, 1, CONTRACTS, load_scenario("AD-11").duration_s, from_second,
    )  # fmt: skip
    assert captured == restored
    assert replay.state_hashes[-1] == original.state_hashes[-1]
    assert json.dumps(replay.records, sort_keys=True) == json.dumps(
        original.records, sort_keys=True
    )
    assert (
        replay.metrics.executed_without_authority == original.metrics.executed_without_authority > 0
    )


def test_an_event_names_one_thing_and_a_mandate_names_known_contracts() -> None:
    base = {
        "schema_version": 1, "id": "AD-11", "title": "t", "track": "C", "duration_s": 600,
        "decision_every_s": 300, "objective": "resilience", "expected": "e",
        "pass_criteria": [{"metric": "it_kwh_lost", "max": 0}],
    }  # fmt: skip
    both = {**base, "timeline": [{"at_s": 0, "note": "n", "authority": {"contracts": []}}]}
    with pytest.raises(ScenarioError, match="exactly one"):
        parse_scenario(both)
    unknown = {**base, "timeline": [{"at_s": 0, "authority": {"contracts": ["no.such.v1"]}}]}
    run = ScenarioRun(
        parse_scenario(unknown), PROFILE, static_allowlist, "STATIC_ALLOWLIST",
        ScriptedAdversarial, 1, CONTRACTS,
    )  # fmt: skip
    with pytest.raises(ValueError, match="no.such.v1"):
        run.run()


def test_the_card_counts_it_for_every_gate() -> None:
    assert CARD_SCHEMA_VERSION == 6
    assert {"proposals_without_authority", "executed_without_authority"} <= set(FAIRNESS_METRICS)


def test_this_is_another_benchmark_version_and_only_in_what_it_adds() -> None:
    """Season 1 runs on benchmark-v1, at its tag. This code is the next version, not yet frozen."""
    frozen = json.loads((REPO / "docs/bench/VERSION.json").read_text(encoding="utf-8"))
    assert not set(AUTHORITY) & set(frozen["scenarios"])
    now = benchmark_version(PROFILE, CONTRACTS, library_ids())
    differing = {key for key in now if now[key] != frozen["version"][key]}
    assert differing == {"scenario_library", "oracle"}
    # Of the oracle's two files only the harness changed: it applies the new event
    # and counts. The file that judges a proposal is the one of benchmark-v1.
    judging = REPO / "packages/agentic-datacenter-scenarios/src/agentic_datacenter/scenarios"
    assert hashlib.sha256((judging / "counterfactual.py").read_bytes()).hexdigest() == (
        "1fc1a9710cb28f3f4ebb0ec4344c048ba3c7cff6e8196b49111cf4ea69d773c8"
    )


# --- why a gate refused, in a word (issue 31, point 2) --------------------------


def test_a_gate_can_say_in_a_word_why_it_refused(revoked: dict[str, RunResult]) -> None:
    """Told apart: refused because nobody authorized it, or refused for something else."""
    result = revoked["checks_premises"]
    unauthorized = [r for r in result.records if r.get("authorized") is False]
    assert unauthorized
    refused_for_it = [r for r in unauthorized if "authority" in r.get("reason_codes", [])]
    assert refused_for_it and all(r["verdict"] == "DENY" for r in refused_for_it)
    assert result.metrics.refused_citing_authority == len(refused_for_it)
    # A proposal refused before the mandate ended was refused for something else.
    earlier = [r for r in result.records if "authorized" not in r and r["verdict"] == "DENY"]
    assert all("authority" not in r.get("reason_codes", []) for r in earlier)


def test_a_gate_that_gives_no_word_has_none_recorded(revoked: dict[str, RunResult]) -> None:
    result = revoked["limits_only"]
    assert all("reason_codes" not in r for r in result.records)
    assert result.metrics.refused_citing_authority == 0


def test_the_words_are_a_fixed_few_and_anything_else_is_other() -> None:
    from agentic_datacenter.governance.gate import REASON_CODES

    assert REASON_CODES == (
        "authority", "limit", "premise", "evidence", "approval", "malformed", "policy", "other",
    )  # fmt: skip

    class _OwnWord(_ChecksPremises):
        def evaluate(self, proposal: Any, premises: Any, actor: Any) -> Decision:
            decision = super().evaluate(proposal, premises, actor)
            if decision.verdict is Verdict.DENY:
                return Decision(
                    Verdict.DENY, decision.decision_ref, proposal.contract_id,
                    reasons=decision.reasons,
                    reason_codes=("because I said so", "premise", "another of mine"),
                )  # fmt: skip
            return decision

    result = _run("AD-13", _OwnWord)
    given = [r["reason_codes"] for r in result.records if "reason_codes" in r]
    # In the order of the list, each once, and what is not on it as "other".
    assert given and all(codes == ["premise", "other"] for codes in given)


def test_the_word_is_on_the_card_and_beside_it() -> None:
    from agentic_datacenter.scenarios.bench import run_benchmark

    decisions: list[dict[str, Any]] = []
    card = run_benchmark(
        PROFILE, CONTRACTS, {"checks_premises": _ChecksPremises}, ["scripted_adversarial"],
        ["AD-13"], [1], horizon_s=300, max_judged=6, allow_unfrozen=True, decisions=decisions,
    )  # fmt: skip
    (run,) = card["runs"]
    assert run["judgements"] and all("reason_codes" in j for j in run["judgements"])
    assert any("authority" in j["reason_codes"] for j in run["judgements"])
    (row,) = card["results"]
    assert row["refused_citing_authority"] == run["metrics"]["refused_citing_authority"] > 0
    assert row["executed_without_authority"] == 0 < row["proposals_without_authority"]
    assert any("authority" in line["reason_codes"] for line in decisions)
    assert all(isinstance(line["reason_codes"], list) for line in decisions)
