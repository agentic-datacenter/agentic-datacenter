"""agentic_datacenter_remora.whatif: REMORA's policy what-if, through remora.sdk only."""

import pytest

pytest.importorskip("remora")

from agentic_datacenter.governance.gate import (  # noqa: E402
    BoundedWrite,
    PremiseResult,
    PremiseSnapshot,
    Proposal,
)
from agentic_datacenter_remora import whatif  # noqa: E402

TAG = "cooling.chw_plant[CHW].chws_sp_c"


def snapshot(value: float, bound_errors: tuple[str, ...] = ()) -> PremiseSnapshot:
    return PremiseSnapshot(
        time_ms=600_000, contract_known=True, risk_tier="R1", approval="none",
        writes=(BoundedWrite(TAG, value, 18.0),), bound_errors=bound_errors,
        premises=(PremiseResult("tes.charge_pct >= 80", True, "100"),),
        rollback_available=True,
    )  # fmt: skip


def test_without_the_sdk_analysis_the_adapter_says_why_and_does_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delattr(whatif.sdk, "what_if", raising=False)
    reason = whatif.unavailable_reason()
    assert reason is not None and "what_if" in reason
    with pytest.raises(RuntimeError, match="what_if"):
        whatif.analyse(
            Proposal("p", "chw.set_supply_setpoint.v1", {"setpoint_c": 18.5}),
            snapshot(18.5),
            max_depth=1,
            max_evaluations=10,
        )


@pytest.mark.skipif(whatif.unavailable_reason() is not None, reason="needs remora.sdk.what_if")
def test_the_two_stages_are_analysed_under_their_own_engines() -> None:
    proposal = Proposal("p", "chw.set_supply_setpoint.v1", {"setpoint_c": 20.5})
    out = whatif.analyse(
        proposal, snapshot(20.5, ("step: too far",)), max_depth=2, max_evaluations=2_000
    )
    stages = {s["stage"]: s for s in out["stages"]}
    assert set(stages) == {"pure_decision", "execution_service"}
    assert stages["pure_decision"]["engine"] == {"library_default": True}
    assert stages["execution_service"]["engine"]["bounded_write_accept"] is True
    assert stages["execution_service"]["observation"]["toolspec_enforced"] is True
    assert stages["pure_decision"]["report"]["hard_guard"] == "malformed_call_blocked"
    assert "reconstruction" in stages["execution_service"]["observation_source"]


def test_an_unformable_proposal_is_not_analysed() -> None:
    proposal = Proposal("p", "no.such.v1", {})
    out = whatif.analyse(
        proposal, PremiseSnapshot(time_ms=0, contract_known=False), max_depth=1, max_evaluations=10
    )
    assert out["stages"] == [] and out["unformable"] == ["no such contract"]


# One proposal inside its bounds and one outside, for each verdict a caller can ask for. The
# proposal inside its bounds is already accepted, so asking for accept searches nothing.
CASES = [
    (18.5, (), "verify"),
    (20.5, ("step: too far",), "accept"),
    (20.5, ("step: too far",), "verify"),
]
# Up to here every case has a stage whose search is stopped, and the agent's search can
# find a path the search over all levers does not get back to (at 56, outside its bounds).
BUDGETS = range(1, 61)
CLAIMS = ("reachable", "confidence_can_lift", "agent_alone_can_reach", "deployment_facts_required")
IMPOSSIBLE = ("cannot reach", "every combination", "up to the search bound")


def stages_of(
    value: float, errors: tuple[str, ...], target: str, budget: int
) -> dict[str, dict[str, object]]:
    out = whatif.analyse(
        Proposal("p", "chw.set_supply_setpoint.v1", {"setpoint_c": value}),
        snapshot(value, errors),
        target=target,
        max_depth=4,
        max_evaluations=budget,
    )
    return {s["stage"]: s for s in out["stages"]}


@pytest.mark.skipif(whatif.unavailable_reason() is not None, reason="needs remora.sdk.what_if")
@pytest.mark.parametrize(("value", "errors", "target"), CASES)
def test_a_search_the_budget_stopped_says_unknown_and_never_impossible(
    value: float, errors: tuple[str, ...], target: str
) -> None:
    reference = stages_of(value, errors, target, 20_000)
    for stage in reference.values():
        assert stage["conclusions"]["search_complete"], "the reference covers the whole space"
    cut_short = 0
    for budget in BUDGETS:
        for name, stage in stages_of(value, errors, target, budget).items():
            read, truth = stage["conclusions"], reference[name]["conclusions"]
            report = stage["report"]
            where = (budget, name)
            # What is found is found whatever the budget, and the full search finds it too.
            for claim in CLAIMS:
                if read[claim] == whatif.YES:
                    assert truth[claim] == whatif.YES, (*where, claim)
            known = [path["levers"] for path in reference[name]["report"]["minimal_paths"]]
            for path in report["minimal_paths"]:
                assert path["levers"] in known, (*where, path["levers"])
            # The claims agree with each other: model signals are the agent's, and a
            # path of the agent's own reaches the target without a deployment fact.
            if read["confidence_can_lift"] == whatif.YES:
                assert read["agent_alone_can_reach"] == whatif.YES, where
            if read["agent_alone_can_reach"] == whatif.YES:
                assert read["reachable"] == whatif.YES, where
                assert read["deployment_facts_required"] == whatif.NO, where
            if read["search_complete"]:
                assert {c: read[c] for c in CLAIMS} == {c: truth[c] for c in CLAIMS}, where
                continue
            cut_short += 1
            # The one negative a found path proves: with a path of the agent's own,
            # no deployment fact is required.
            proved = (
                {"deployment_facts_required"}
                if read["agent_alone_can_reach"] == whatif.YES
                else set()
            )
            for claim in CLAIMS:
                assert read[claim] != whatif.NO or claim in proved, (*where, claim)
            text = str(stage["summary"])
            for phrase in IMPOSSIBLE:
                assert phrase not in text, (*where, phrase)
            # The text says what the reading says.
            found_nothing = "unknown whether one exists" in text
            assert found_nothing is (read["reachable"] == whatif.UNKNOWN), where
            agent_line = next(line for line in text.splitlines() if line.startswith("agent alone"))
            assert ("reach" in agent_line and "via" in agent_line) is (
                read["agent_alone_can_reach"] == whatif.YES
            ), where
    assert cut_short, "every case has a search that these budgets stop"


@pytest.mark.skipif(whatif.unavailable_reason() is not None, reason="needs remora.sdk.what_if")
def test_a_complete_search_keeps_remoras_own_text_and_its_negatives() -> None:
    stages = stages_of(20.5, ("step: too far",), "accept", 20_000)
    pure = stages["pure_decision"]
    assert pure["conclusions"]["search_complete"] is True
    assert pure["conclusions"]["confidence_can_lift"] == whatif.NO
    assert pure["conclusions"]["agent_alone_can_reach"] == whatif.YES
    assert "tried in every combination" in str(pure["summary"])


def report_of(**changed: object) -> dict[str, object]:
    report: dict[str, object] = {
        "already_at_target": False, "reachable": False, "confidence_can_lift": False,
        "agent_alone_can_reach": False, "deployment_facts_required": False,
        "minimal_paths": [], "search": {"exhausted": True},
    }  # fmt: skip
    return {**report, **changed}


def test_a_negative_is_a_no_only_when_the_whole_space_was_searched() -> None:
    assert whatif.conclusions(report_of())["reachable"] == whatif.NO
    stopped = whatif.conclusions(report_of(search={"exhausted": False}))
    assert stopped["search_complete"] is False
    assert {stopped[c] for c in CLAIMS} == {whatif.UNKNOWN}


def test_paths_that_all_need_a_deployment_fact_prove_nothing_about_the_agent_when_cut_short() -> (
    None
):
    found = {"reachable": True, "deployment_facts_required": True, "minimal_paths": [{}]}
    assert whatif.conclusions(report_of(**found))["deployment_facts_required"] == whatif.YES
    stopped = whatif.conclusions(report_of(**found, search={"exhausted": False}))
    assert stopped["reachable"] == whatif.YES
    assert stopped["agent_alone_can_reach"] == whatif.UNKNOWN
    assert stopped["deployment_facts_required"] == whatif.UNKNOWN
    alone = report_of(**found, agent_alone_can_reach=True, search={"exhausted": False})
    assert whatif.conclusions(alone)["deployment_facts_required"] == whatif.NO


@pytest.mark.parametrize("exhausted", [True, False])
def test_a_path_found_by_one_search_counts_for_the_claims_it_implies(exhausted: bool) -> None:
    # The agent's search found a path; the search over all levers did not get back to it.
    search = {"exhausted": exhausted, "max_depth": 2}
    agent = whatif.conclusions(report_of(agent_alone_can_reach=True, search=search))
    assert agent["reachable"] == whatif.YES and agent["deployment_facts_required"] == whatif.NO
    # Model signals alone reach the target with more changes than the other searches may make.
    model = whatif.conclusions(report_of(confidence_can_lift=True, search=search))
    assert model["agent_alone_can_reach"] == whatif.YES and model["reachable"] == whatif.YES
    assert model["deployment_facts_required"] == whatif.NO and model["max_depth"] == 2


@pytest.mark.skipif(whatif.unavailable_reason() is not None, reason="needs remora.sdk.what_if")
def test_the_text_of_a_stopped_search_does_not_deny_the_path_it_found() -> None:
    # At this budget the agent's search finds a path and the search over all levers is
    # stopped before it gets back to it: REMORA's report has reachable False.
    stage = stages_of(20.5, ("step: too far",), "verify", 56)["execution_service"]
    assert stage["report"]["reachable"] is False and stage["report"]["without_deployment"]
    assert stage["conclusions"]["reachable"] == whatif.YES
    text = str(stage["summary"])
    assert "VERIFY can be reached" in text and "unknown whether one exists" not in text
