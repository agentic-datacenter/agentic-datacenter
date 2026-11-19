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
    "reason_codes",
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
