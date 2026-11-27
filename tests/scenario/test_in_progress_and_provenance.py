"""A step in progress when its mandate ends, who acted for whom, and what can be verified.

Four things asked of a test site for governed action in the physical world
(ADR 0041): what becomes of a step that is under way when authority is
withdrawn; a record of whose mandate each action was taken under; readings a
gate can check the origin of; and a receipt whose signature is checked.
"""

from __future__ import annotations

import base64
import json
import shlex
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance import attest
from agentic_datacenter.governance.bindings.http_gate import command_from_environment
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.control_path import IN_PROGRESS_S, MANDATE_ENDED_IN_PROGRESS
from agentic_datacenter.governance.interop import verify_receipts
from agentic_datacenter.scenarios.agents import ScriptedAdversarial, ScriptedBenign
from agentic_datacenter.scenarios.harness import RunResult, ScenarioRun, run_scenario
from agentic_datacenter.scenarios.scenario import Scenario, load_scenario, parse_scenario
from agentic_datacenter.scenarios.trace import action_trace, render_trace

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
ADAPTER = REPO / "examples/command-gate/adapter.py"
POD = "pod.set_supply_air_setpoint.v1"
TAG = "cooling.pod[16].supply_air_sp_c"
SEED = "11" * 32


def _starter(monkeypatch: pytest.MonkeyPatch, **env: str) -> Any:
    monkeypatch.setenv("ADC_GATE_COMMAND", shlex.join([sys.executable, str(ADAPTER)]))
    monkeypatch.setenv("ADC_GATE_NAME", "starter")
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    return command_from_environment()


def _run(scenario: Scenario | str, gate: Any, agent: Any = None) -> RunResult:
    scenario = load_scenario(scenario) if isinstance(scenario, str) else scenario
    return run_scenario(
        scenario, PROFILE, gate, "DECISION_ONLY", agent or ScriptedBenign(), 1, CONTRACTS
    )


def _order(result: RunResult) -> dict[str, Any]:
    return next(r for r in result.records if str(r["rationale"]).startswith("WO-"))


def _writes(result: RunResult, tag: str = TAG) -> list[tuple[str, Any, Any]]:
    return [
        (str(c["role"]), c["old"], c["new"])
        for c in result.change_log
        if c["tag"] == tag and c["accepted"]
    ]


# --- a step in progress when its mandate ends ------------------------------------------


@pytest.mark.req("ADC-AUT-009")
@pytest.mark.parametrize("agent", [ScriptedBenign, ScriptedAdversarial])
def test_a_step_in_progress_is_undone_when_its_mandate_is_withdrawn(
    monkeypatch: pytest.MonkeyPatch, agent: type
) -> None:
    result = _run("AD-20", _starter(monkeypatch), agent())
    order = _order(result)
    assert order["authorized"] is True and order["verdict"] == "ALLOW"
    assert order["outcome"] == "ROLLED_BACK"
    assert str(order["outcome_detail"]).startswith(MANDATE_ENDED_IN_PROGRESS)
    assert _writes(result) == [("agent", 22.0, 23.0), ("operator", 23.0, 22.0)]
    assert result.metrics.executed_without_authority == 0
    assert result.passed, result.failed_criteria


@pytest.mark.req("ADC-AUT-009")
def test_a_step_that_has_settled_stands_when_the_mandate_is_withdrawn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = load_scenario("OP-17")
    order_at, withdrawn_at = (e.at_s for e in scenario.timeline[1:])
    assert withdrawn_at - order_at > IN_PROGRESS_S
    result = _run(scenario, _starter(monkeypatch))
    assert _order(result)["outcome"] == "APPLIED"
    assert _writes(result) == [("agent", 22.0, 23.0)]
    assert result.metrics.rolled_back == 0 and result.passed, result.failed_criteria


@pytest.mark.req("ADC-AUT-009")
def test_a_step_whose_undoing_would_move_away_from_safety_is_left_standing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = load_scenario("AD-20").model_dump(mode="json")
    data["timeline"][1]["work_order"]["arguments"]["setpoint_c"] = 21.0  # colder: the safe way
    data["pass_criteria"] = [c for c in data["pass_criteria"] if c["metric"] != "rolled_back"]
    result = _run(parse_scenario(data), _starter(monkeypatch))
    assert _order(result)["outcome"] == "APPLIED"
    assert _writes(result) == [("agent", 22.0, 21.0)]
    assert result.metrics.rolled_back == 0


@pytest.mark.req("ADC-AUT-009")
def test_a_mandate_that_expires_or_ends_at_its_source_undoes_a_step_in_progress(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    for how in ("expires", "source"):
        data = load_scenario("AD-20").model_dump(mode="json")
        first, order, _ = data["timeline"]
        if how == "expires":
            first["authority"]["expires_after_s"] = 1260
            data["timeline"] = [first, order]
        else:
            giver = {"at_s": 0, "authority": {
                "principal": "orchestrator-1", "contracts": "all", "by": "operator-1"}}  # fmt: skip
            first["authority"].update(by="orchestrator-1", delegated=True)
            end = {"at_s": 1260, "authority": {
                "principal": "orchestrator-1", "contracts": [], "by": "operator-1"}}  # fmt: skip
            data["timeline"] = [giver, first, order, end]
        result = _run(parse_scenario(data), _starter(monkeypatch))
        order_record = _order(result)
        assert order_record["outcome"] == "ROLLED_BACK", how
        assert str(order_record["outcome_detail"]).startswith(MANDATE_ENDED_IN_PROGRESS)


@pytest.mark.req("ADC-AUT-009")
def test_a_run_that_sets_no_mandate_undoes_nothing_for_want_of_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = load_scenario("OP-17").model_dump(mode="json")
    data["timeline"] = [data["timeline"][1]]
    result = _run(parse_scenario(data), _starter(monkeypatch))
    assert _order(result)["outcome"] == "APPLIED" and result.metrics.rolled_back == 0


# --- who acted for whom ------------------------------------------------------------------


@pytest.mark.req("ADC-AUT-010")
def test_the_trace_names_the_chain_of_mandates_an_action_was_taken_under(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = load_scenario("OP-16")
    result = _run(scenario, _starter(monkeypatch))
    entries = action_trace(result.records, result.change_log, scenario)
    order = next(e for e in entries if e["contract"] == "chw.rotate_lead_chiller.v1")
    chain = order["acted_for"]
    assert [(c["principal"], c["given_by"], c["passed_on"]) for c in chain] == [
        ("agent-1", "orchestrator-1", True), ("orchestrator-1", "operator-1", False),
    ]  # fmt: skip
    assert chain[0]["contracts"] == sorted(["chw.rotate_lead_chiller.v1", POD])
    assert chain[1]["contracts"] == "all" and "expires_at_ms" in chain[1]
    text = render_trace(entries, scenario)
    assert (
        "Acted under the mandate of: agent-1, passed on by orchestrator-1; "
        "orchestrator-1, given by operator-1." in text
    )
    assert entries == action_trace(result.records, result.change_log, scenario)


@pytest.mark.req("ADC-AUT-010")
def test_a_change_at_the_source_while_a_step_is_open_is_in_its_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = load_scenario("AD-20").model_dump(mode="json")
    first, order, _ = data["timeline"]
    giver = {"at_s": 0, "authority": {
        "principal": "orchestrator-1", "contracts": "all", "by": "operator-1"}}  # fmt: skip
    first["authority"].update(by="orchestrator-1", delegated=True)
    ended = {"principal": "orchestrator-1", "contracts": [], "by": "operator-1"}
    end = {"at_s": 1260, "authority": ended}
    data["timeline"] = [giver, first, order, end]
    scenario = parse_scenario(data)
    result = _run(scenario, _starter(monkeypatch))
    entry = next(
        e for e in action_trace(result.records, result.change_log, scenario)
        if e["links"][0].get("rationale", "").startswith("WO-")
    )  # fmt: skip
    steps = [(link["step"], link.get("principal")) for link in entry["links"]]
    assert ("mandate_change", "orchestrator-1") in steps
    assert entry["links"][-1]["status"] == "ROLLED_BACK"
    undo = [link for link in entry["links"] if link["step"] == "command"][-1]
    assert (undo["old"], undo["new"]) == (23.0, 22.0)


@pytest.mark.req("ADC-AUT-010")
def test_a_trace_of_a_run_that_sets_no_mandate_is_the_trace_it_was(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scenario = load_scenario("OP-18")
    result = _run(scenario, _starter(monkeypatch))
    entries = action_trace(result.records, result.change_log, scenario)
    assert entries and all("acted_for" not in e for e in entries)
    assert all(e["signature"] == "not_checked" for e in entries)


# --- readings a gate can check the origin of -----------------------------------------------


def _context(spoofed: dict[str, Any] | None = None) -> dict[str, Any]:
    run = ScenarioRun(
        load_scenario("OP-09"), PROFILE, lambda contracts: None, "UNGOVERNED", None, 1, CONTRACTS
    )
    from agentic_datacenter.governance.interop import plant_context
    from agentic_datacenter.supervisory.overview import Overview

    points = run.world.points
    return plant_context(points, Overview(points, []), run.world.path.now_ms(), spoofed=spoofed)


@pytest.mark.req("ADC-INT-011")
def test_every_reading_of_the_context_is_signed_by_its_source() -> None:
    context = _context()
    rows = [r for group in ("temperatures", "load", "interlocks") for r in context[group]]
    assert len(rows) > 20
    names = {s["name"] for s in context["sources"]}
    for row in rows:
        assert row["source"] == attest.source_of(row["tag"]) and row["source"] in names
        assert attest.reading_not_verified(row, context["sources"]) == ""
        assert json.loads(row["reading"]) == {k: row[k] for k in attest.READING}
    changed = {**rows[0], "value": 99.0}
    assert (
        attest.reading_not_verified(changed, context["sources"]) == "the row is not what was signed"
    )
    assert attest.reading_not_verified(rows[0], []) == "source is not known"
    assert context == _context()


@pytest.mark.req("ADC-INT-011")
def test_a_spoofed_reading_names_its_source_and_does_not_verify() -> None:
    tag = "electrical.power_train[A].alarm_lockout"
    context = _context({tag: True})
    (row,) = [r for r in context["interlocks"] if r["tag"] == tag]
    assert row["value"] is True and row["source"] == "electrical.power_train[A]"
    assert attest.reading_not_verified(row, context["sources"]) == "signature does not verify"
    others = [r for r in context["interlocks"] if r["tag"] != tag]
    assert all(attest.reading_not_verified(r, context["sources"]) == "" for r in others)


@pytest.mark.req("ADC-INT-011")
def test_a_gate_that_checks_readings_lets_the_sound_step_through_and_one_that_does_not_blocks_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checks = _run("OP-18", _starter(monkeypatch, ADC_GATE_CONTEXT="1", ADC_VERIFY_READINGS="1"))
    order = _order(checks)
    assert order["verdict"] == "ALLOW" and order["outcome"] == "APPLIED"
    monkeypatch.delenv("ADC_VERIFY_READINGS")
    trusts = _run("OP-18", _starter(monkeypatch, ADC_GATE_CONTEXT="1"))
    order = _order(trusts)
    assert order["verdict"] == "DENY" and "interlock locked out" in order["reasons"][0]
    # The plant never had the lockout: what the simulator established is what it was.
    assert all(p["holds"] is True for p in order["premises"])


# --- a receipt whose signature is checked ---------------------------------------------------


def _public(monkeypatch: pytest.MonkeyPatch) -> str:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    key = Ed25519PrivateKey.from_private_bytes(bytes.fromhex(SEED))
    return base64.b64encode(attest.public_bytes(key)).decode("ascii")


@pytest.mark.req("ADC-INT-012")
def test_a_signed_receipt_is_checked_during_the_run_and_the_trace_says_so(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipts = tmp_path / "receipts.jsonl"
    public = _public(monkeypatch)
    gate = _starter(
        monkeypatch, ADC_RECEIPTS_FILE=str(receipts), ADC_RECEIPTS_KEY_SEED=SEED,
        ADC_GATE_RECEIPT_KEY=public,
    )  # fmt: skip
    assert gate.receipt_keys == (public,)
    scenario = load_scenario("OP-17")
    result = _run(scenario, gate)
    decided = [r for r in result.records if r["verdict"] is not None]
    assert decided and all(r["gate_detail"]["receipt_signature"] == "verified" for r in decided)
    entries = action_trace(result.records, result.change_log, scenario)
    assert {e["signature"] for e in entries} == {"verified"}
    lines = [json.loads(line) for line in receipts.read_text().splitlines()]
    report = verify_receipts(result.records, lines, public_keys=(public,))
    assert report.ok and report.signed and not report.unsigned and not report.bad_signature
    assert set(report.signed) == set(report.matched)
    # A line changed after it was signed, and a key that is not the system's.
    lines[0] = {**lines[0], "verdict": "ALLOW" if lines[0].get("verdict") != "ALLOW" else "DENY"}
    changed = verify_receipts(result.records, lines, public_keys=(public,))
    assert not changed.ok and changed.bad_signature == [lines[0]["correlation_id"]]
    other = base64.b64encode(attest.public_bytes(attest.source_key("someone-else"))).decode()
    assert not verify_receipts(result.records, lines[1:], public_keys=(other,)).ok


@pytest.mark.req("ADC-INT-012")
def test_an_unsigned_receipt_is_said_to_be_unsigned_and_a_wrong_key_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    receipts = tmp_path / "receipts.jsonl"
    public = _public(monkeypatch)
    gate = _starter(monkeypatch, ADC_RECEIPTS_FILE=str(receipts), ADC_GATE_RECEIPT_KEY=public)
    result = _run("OP-17", gate)
    decided = [r for r in result.records if r["verdict"] is not None]
    assert {r["gate_detail"]["receipt_signature"] for r in decided} == {"not_signed"}
    lines = [json.loads(line) for line in receipts.read_text().splitlines()]
    report = verify_receipts(result.records, lines, public_keys=(public,))
    assert report.ok and report.unsigned and not report.signed
    assert "signatures" not in verify_receipts(result.records, lines).as_dict()
    assert attest.receipt_signature({"a": 1}, ()) == attest.NOT_CHECKED
    signed = attest.sign_receipt({"a": 1}, attest.source_key("mine"))
    mine = base64.b64encode(attest.public_bytes(attest.source_key("mine"))).decode()
    assert attest.receipt_signature(signed, (mine,)) == attest.VERIFIED
    assert attest.receipt_signature({**signed, "a": 2}, (mine,)) == attest.FAILED
    assert attest.receipt_signature(signed, (public,)) == attest.FAILED
