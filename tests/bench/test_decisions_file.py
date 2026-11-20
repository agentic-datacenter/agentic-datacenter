"""What each gate decided and why is written beside the card, not into it (issue 31)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.static_allowlist import StaticAllowlist
from agentic_datacenter.governance.bindings.static_allowlist import create as static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.bench import DECISIONS_NAME, run_benchmark, write_decisions
from agentic_datacenter.scenarios.cli import bench

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
KEYS = {
    "run_id", "proposal_id", "time_ms", "contract_id", "verdict", "reasons", "outcome",
    "outcome_detail", "contract_errors", "limit_errors", "premises_not_established",
    "reason_codes", "grounds",
}  # fmt: skip


def _run(**more: Any) -> dict[str, Any]:
    return run_benchmark(
        PROFILE, CONTRACTS, {"static_allowlist": static_allowlist}, ["scripted_adversarial"],
        ["AD-03"], [1], 1200, counterfactual=False, allow_unfrozen=True, **more,
    )  # fmt: skip


def test_the_decisions_are_collected_and_the_card_is_the_card_without_them() -> None:
    plain = _run()
    collected: list[dict[str, Any]] = []
    with_decisions = _run(decisions=collected)
    assert json.dumps(with_decisions, sort_keys=True) == json.dumps(plain, sort_keys=True)
    assert "decisions" not in json.dumps(plain)
    assert collected and all(set(line) == KEYS for line in collected)
    (run,) = plain["runs"]
    assert {line["run_id"] for line in collected} == {run["run_id"]}
    assert [line["time_ms"] for line in collected] == sorted(line["time_ms"] for line in collected)


def test_every_decision_carries_the_gates_own_reasons() -> None:
    collected: list[dict[str, Any]] = []
    _run(decisions=collected)
    assert all(
        line["reasons"] and all(isinstance(r, str) for r in line["reasons"]) for line in collected
    )
    # A gate with nothing on its list refuses everything, and says why each time.
    denied: list[dict[str, Any]] = []
    run_benchmark(
        PROFILE, CONTRACTS, {"empty_list": lambda contracts: StaticAllowlist([])},
        ["scripted_adversarial"], ["AD-03"], [1], 1200, counterfactual=False,
        allow_unfrozen=True, decisions=denied,
    )  # fmt: skip
    assert denied and {line["verdict"] for line in denied} == {"DENY"}
    assert all("contract is not on the allowlist" in line["reasons"] for line in denied)
    assert all(line["outcome"] != "APPLIED" for line in denied)


def test_runs_made_in_processes_of_their_own_give_the_same_decisions() -> None:
    one: list[dict[str, Any]] = []
    several: list[dict[str, Any]] = []
    _run(decisions=one)
    _run(decisions=several, jobs=2)
    assert several == one


def test_the_file_is_one_decision_a_line_beside_the_card(tmp_path: Path) -> None:
    collected: list[dict[str, Any]] = []
    _run(decisions=collected)
    path = write_decisions(collected, tmp_path)
    assert path == tmp_path / DECISIONS_NAME == tmp_path / "decisions.jsonl"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line) for line in lines] == collected


def test_the_command_writes_the_file_and_the_record_covers_it(tmp_path: Path) -> None:
    out = tmp_path / "bench"
    arguments = [
        "run", "--scenario", "AD-03", "--gate", "static_allowlist", "--agent",
        "scripted_adversarial", "--seconds", "1200", "--no-counterfactual", "--allow-unfrozen",
        "--out", str(out),
    ]  # fmt: skip
    assert bench(arguments) == 0
    assert (out / "result_card.json").is_file() and (out / "decisions.jsonl").is_file()
    assert bench(["record", str(out)]) == 0
    record = json.loads((out / "provenance.json").read_text(encoding="utf-8"))
    assert "decisions.jsonl" in record["files"]


# --- every refusal has a reason on the card, whatever the gate (issue 31, point 2) ---


def _authority_run(make_gate: Any, **more: Any) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    decisions: list[dict[str, Any]] = []
    card = run_benchmark(
        PROFILE, CONTRACTS, {"gate": make_gate}, ["scripted_adversarial"], ["AD-13"], [1],
        horizon_s=300, allow_unfrozen=True, decisions=decisions, **more,
    )  # fmt: skip
    return card, decisions


def test_a_gate_that_gives_no_codes_still_has_grounds_for_each_refusal() -> None:
    """What was wrong with the step, as established here, is on the card beside the gate's word."""
    card, decisions = _authority_run(static_allowlist)
    (run,) = card["runs"]
    assert all(j["reason_codes"] == [] for j in run["judgements"])
    assert all(isinstance(j["grounds"], list) for j in run["judgements"])
    # In AD-13 the agent holds a mandate for POD supply air only.
    outside = [j for j in run["judgements"] if j["contract_id"] != "pod.set_supply_air_setpoint.v1"]
    assert outside and all("authority" in j["grounds"] for j in outside)
    assert all("grounds" in line for line in decisions)


def test_the_grounds_name_each_way_a_step_was_wrong() -> None:
    from agentic_datacenter.scenarios.bench import grounds

    assert grounds(
        {"authorized": False, "premises": [], "contract_errors": [], "limit_errors": []}
    ) == ["authority"]
    record = {
        "authorized": False,
        "contract_errors": ["range: setpoint_c 30.0 is above 18.0", "unknown argument: x"],
        "limit_errors": ["rate: more than 2 per hour"],
        "premises": [
            {"expr": "authority(agent-1, c)", "holds": False},
            {"expr": "redundancy.chillers >= N", "holds": False},
            {"expr": "tes.charge_pct >= 80", "holds": None},
        ],
    }
    assert grounds(record) == ["authority", "limit", "premise", "evidence", "malformed"]
    assert grounds({"premises": [{"expr": "x", "holds": True}]}) == []
    assert grounds({"was_unknown": True, "contract_errors": []}) == ["malformed"]


def test_every_refusal_of_a_run_is_counted_on_the_card_judged_or_not() -> None:
    """With a sample judged, most refusals have no judgement. The run still counts them all."""
    card, decisions = _authority_run(static_allowlist, max_judged=2)
    (run,) = card["runs"]
    refused = [d for d in decisions if d["verdict"] != "ALLOW"]
    assert len(run["judgements"]) == 2 < len(decisions)
    tally = run["refusals"]
    assert tally["total"] == len(refused) > 0
    assert sum(tally["by_reason_code"].values()) >= tally["total"]
    assert tally["by_reason_code"] == {"none": len(refused)}
    assert tally["by_ground"]["authority"] == sum("authority" in d["grounds"] for d in refused)
    assert tally["by_ground"].get("none", 0) == sum(not d["grounds"] for d in refused)


def test_the_gates_own_codes_are_counted_beside_the_grounds() -> None:
    from agentic_datacenter.governance.gate import Decision, Verdict

    class _SaysWhy:
        name, profile = "says_why", "STATIC_ALLOWLIST"

        def __init__(self, contracts: ContractLibrary) -> None:
            self.inner = static_allowlist(contracts)

        def evaluate(self, proposal: Any, premises: Any, actor: Any) -> Decision:
            decision = self.inner.evaluate(proposal, premises, actor)
            failing = [p.expr for p in premises.premises if p.holds is not True]
            if decision.verdict is Verdict.ALLOW and failing:
                return Decision(
                    Verdict.DENY, decision.decision_ref, proposal.contract_id,
                    reasons=("no mandate",), reason_codes=("authority",),
                )  # fmt: skip
            return decision

        def record_outcome(self, decision_ref: str, outcome: Any) -> None:
            self.inner.record_outcome(decision_ref, outcome)

    card, decisions = _authority_run(_SaysWhy)
    (run,) = card["runs"]
    cited = sum("authority" in d["reason_codes"] for d in decisions if d["verdict"] != "ALLOW")
    assert cited > 0 and run["refusals"]["by_reason_code"]["authority"] == cited
    assert run["refusals"]["total"] == sum(d["verdict"] != "ALLOW" for d in decisions)
