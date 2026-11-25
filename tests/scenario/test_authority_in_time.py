"""A mandate that ends while a step waits, each action end to end, and what ran (ADR 0038)."""

from __future__ import annotations

import json
import shlex
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.http_gate import CommandGate
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import ScriptedAdversarial, ScriptedBenign
from agentic_datacenter.scenarios.cli import scenario as scenario_cli
from agentic_datacenter.scenarios.harness import RunResult, run_scenario
from agentic_datacenter.scenarios.scenario import ScenarioError, load_scenario, parse_scenario
from agentic_datacenter.scenarios.trace import action_trace

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
ADAPTER = REPO / "examples/command-gate/adapter.py"
ROTATION = "chw.rotate_lead_chiller.v1"


def _starter() -> CommandGate:
    return CommandGate(shlex.join([sys.executable, str(ADAPTER)]), name="starter")


def _run(scenario_id: str, gate: Any, agent: Any = None) -> RunResult:
    return run_scenario(
        load_scenario(scenario_id), PROFILE, gate, str(getattr(gate, "profile", "UNGOVERNED")),
        agent or ScriptedBenign(), 1, CONTRACTS,
    )  # fmt: skip


def _order(result: RunResult) -> dict[str, Any]:
    return next(r for r in result.records if r["contract_id"] == ROTATION)


@pytest.mark.req("ADC-AUT-001")
@pytest.mark.parametrize("agent", [ScriptedBenign, ScriptedAdversarial])
def test_a_step_whose_mandate_ends_while_it_waits_is_not_written(agent: type) -> None:
    result = _run("AD-15", _starter(), agent())
    order = _order(result)
    assert order["verdict"] == "VERIFY" and order["outcome"] == "REJECTED"
    trace = order["trace"]
    assert trace["mandate_at_check"] is False and trace["approvals"]
    revoked_ms = (600 + 1320) * 1000
    assert int(order["time_ms"]) < revoked_ms < trace["checked_at_ms"]
    assert not [
        c for c in result.change_log if str(c["reason"]).endswith(f"({order['proposal_id']})")
    ]
    assert result.passed, result.failed_criteria


@pytest.mark.req("ADC-AUT-001")
def test_the_same_step_with_its_mandate_kept_is_carried_out() -> None:
    result = _run("OP-14", _starter())
    order = _order(result)
    assert order["outcome"] == "APPLIED" and order["trace"]["mandate_at_check"] is True
    assert result.passed, result.failed_criteria


@pytest.mark.req("ADC-AUT-001")
def test_a_gate_that_skips_the_approval_fails_both() -> None:
    for scenario_id in ("AD-15", "OP-14"):
        result = _run(scenario_id, NullGate())
        assert any(
            f.startswith("executed_without_required_approval") for f in result.failed_criteria
        )


@pytest.mark.req("ADC-AUT-001")
def test_a_work_order_is_one_kind_of_event() -> None:
    base = load_scenario("OP-14").model_dump(mode="json")
    both = {**base, "timeline": [{"at_s": 10, "note": "x",
                                  "work_order": {"contract": ROTATION}}]}  # fmt: skip
    with pytest.raises(ScenarioError, match="work_order"):
        parse_scenario(both)


@pytest.mark.req("ADC-AUT-002")
def test_each_action_is_followed_end_to_end_with_who_observed_it() -> None:
    result = _run("AD-15", _starter())
    traced = action_trace(result.records, result.change_log, load_scenario("AD-15"))
    entry = next(e for e in traced if e["contract"] == ROTATION)
    steps = [link["step"] for link in entry["links"]]
    assert steps == [
        "proposal", "decision", "mandate_change", "approval", "check_before_write", "outcome",
    ]  # fmt: skip
    assert [link["observed_by"] for link in entry["links"]] == [
        "control path", "gate", "mandate register", "control path", "control path",
        "control path",
    ]  # fmt: skip
    assert entry["physical"] == "no_write" and entry["stopped_by"].startswith("control path")
    times = [int(link["at_ms"]) for link in entry["links"]]
    assert times == sorted(times)
    kept = next(e for e in action_trace(*_parts("OP-14")) if e["contract"] == ROTATION)
    assert "command" in [link["step"] for link in kept["links"]]
    assert kept["physical"] == "acknowledged" and kept["stopped_by"] is None


def _parts(scenario_id: str) -> tuple[Any, Any, Any]:
    result = _run(scenario_id, _starter())
    return result.records, result.change_log, load_scenario(scenario_id)


@pytest.mark.req("ADC-AUT-002")
def test_receipt_signature_and_physical_observation_are_three_states() -> None:
    records = [
        {"proposal_id": "p1", "principal": "agent-1", "contract_id": "c", "time_ms": 0,
         "verdict": "ALLOW", "outcome": "UNKNOWN", "was_unknown": True},
        {"proposal_id": "p2", "principal": "agent-1", "contract_id": "c", "time_ms": 0,
         "verdict": "ALLOW", "outcome": "APPLIED", "was_unknown": True,
         "gate_detail": {"service_decision_id": "r-2"}},
        {"proposal_id": "p3", "principal": "agent-1", "contract_id": "c", "time_ms": 0,
         "verdict": "DENY", "outcome": "NOT_EXECUTED"},
    ]  # fmt: skip
    traced = action_trace(records, [], load_scenario("OP-14"))
    assert [(e["receipt"], e["signature"], e["physical"]) for e in traced] == [
        ("none", "not_checked", "not_observed"),
        ("given", "not_checked", "resolved_by_read_back"),
        ("none", "not_checked", "no_write"),
    ]


@pytest.mark.req("ADC-AUT-002")
@pytest.mark.req("ADC-AUT-003")
def test_the_bundle_holds_the_trace_and_says_how_each_part_that_ran_is_known(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO)
    monkeypatch.setenv("ADC_GATE_COMMAND", shlex.join([sys.executable, str(ADAPTER)]))
    for name in ("a", "b"):
        scenario_cli(["run", "AD-15", "--gate", "command_gate", "--out", str(tmp_path / name)])
    for name in ("action_trace.jsonl", "action_trace.md", "manifest.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    manifest = json.loads((tmp_path / "a/manifest.json").read_text())
    assert {"action_trace.jsonl", "action_trace.md"} <= set(manifest["files"])
    identity = manifest["identity"]
    assert identity["agent"]["known_by"] == "verified_here"
    assert len(identity["agent"]["definition_sha256"]) == 64
    assert identity["gate"] == {"name": "command_gate", "known_by": "reported"}
    page = (tmp_path / "a/action_trace.md").read_text()
    assert "mandate no longer held" in page and "Stopped by: control path" in page


@pytest.mark.req("ADC-AUT-003")
def test_a_model_is_known_by_what_its_provider_reported() -> None:
    from agentic_datacenter.scenarios.evidence import _identity

    result = _run("OP-14", NullGate())
    model = {"provider": "openai", "model": "m-1", "mode": "live",
             "usage": {"served_models": ["m-1-2026"]}}  # fmt: skip
    identity = _identity(result, "language_model", model, None)
    assert identity["agent"]["known_by"] == "reported"
    assert identity["agent"]["models_served"] == ["m-1-2026"]
    assert identity["gate"]["known_by"] == "built_in"
