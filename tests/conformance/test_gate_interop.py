"""A governance system from outside connects at a low threshold, and its receipts can be checked.

ADR 0036: a correlation shared by the request and its outcome, a content
address of the action, a fixed UTC anchor, an optional read-only sample of the
plant, and a local check of exported receipts.
"""

from __future__ import annotations

import json
import re
import shlex
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.http_gate import (
    HttpGate,
    HttpGateConfigError,
    command_from_environment,
    read_verdict,
)
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.interop import (
    MAX_RECEIPT_BYTES,
    action_ref,
    utc,
    verify_receipts,
)
from agentic_datacenter.scenarios.agents import ScriptedBenign
from agentic_datacenter.scenarios.cli import gate as gate_cli
from agentic_datacenter.scenarios.cli import scenario as scenario_cli
from agentic_datacenter.scenarios.harness import run_scenario
from agentic_datacenter.scenarios.scenario import load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
ADAPTER = REPO / "examples/command-gate/adapter.py"
HASH = re.compile(r"sha256:[0-9a-f]{64}")


class Captured(HttpGate):
    """A served gate whose service is this object: it allows, and keeps every message."""

    def __init__(self, answer: Mapping[str, Any] | None = None, **options: Any) -> None:
        super().__init__("http://127.0.0.1:9", name="captured", **options)
        self.sent: list[tuple[str, dict[str, Any]]] = []
        self._extra = dict(answer or {})

    def _post(self, path: str, body: Mapping[str, Any]) -> Any:
        self.sent.append((path, json.loads(json.dumps(body))))
        return {"schema": "agentic_datacenter.gate.http/1", "verdict": "permit",
                "reasons": ["captured"], **self._extra}  # fmt: skip


def _run(gate: HttpGate, seconds: int = 900) -> Any:
    return run_scenario(
        load_scenario("OP-03"), PROFILE, gate, "DECISION_ONLY", ScriptedBenign(), 1, CONTRACTS,
        seconds,
    )  # fmt: skip


@pytest.mark.req("ADC-INT-001")
def test_the_request_and_its_outcome_carry_the_same_correlation() -> None:
    gate = Captured(answer={"decision_id": "rcpt-1"})
    result = _run(gate)
    evaluates = [b for p, b in gate.sent if p == "/evaluate"]
    outcomes = [b for p, b in gate.sent if p == "/outcome"]
    assert evaluates and outcomes
    for body in evaluates:
        tie = body["correlation"]
        assert HASH.fullmatch(tie["action_ref"])
        assert tie["correlation_id"] == f"{body['session']}/{body['proposal']['proposal_id']}"
        assert tie["issued_at"] == utc(body["premises"]["time_ms"])
    told = {b["correlation"]["correlation_id"]: b["correlation"] for b in evaluates}
    for body in outcomes:
        assert body["action_ref"] == told[body["correlation_id"]]["action_ref"]
        assert body["proposal_id"] == body["correlation_id"].rsplit("/", 1)[1]
        assert body["verdict"] == "ALLOW"
    record = result.records[0]
    detail = record["gate_detail"]
    assert detail["service_decision_id"] == "rcpt-1" and detail["action_ref"] in {
        t["action_ref"] for t in told.values()
    }


@pytest.mark.req("ADC-INT-002")
def test_the_action_ref_is_made_again_from_the_record() -> None:
    record = _run(Captured()).records[0]
    detail = record["gate_detail"]
    assert detail["action_ref"] == action_ref(
        detail["session"], record["proposal_id"], record["contract_id"], record["arguments"],
        record["principal"], record["time_ms"],
    )  # fmt: skip


@pytest.mark.req("ADC-INT-002")
def test_receipts_are_checked_against_proposal_verdict_and_outcome() -> None:
    records = _run(Captured(answer={"decision_id": "rcpt-1"})).records
    first = records[0]
    cid, ref = first["gate_detail"]["correlation_id"], first["gate_detail"]["action_ref"]
    good = [
        {"correlation_id": cid, "action_ref": ref, "verdict": "permit", "decision_id": "rcpt-1"},
        {"correlation_id": cid, "outcome": first["outcome"]},
    ]
    report = verify_receipts(records, good, read_verdict)
    assert report.ok and cid in report.matched
    for wrong, field in (
        ({"action_ref": "sha256:" + "0" * 64}, "action_ref"),
        ({"verdict": "DENY"}, "verdict"),
        ({"outcome": "ROLLED_BACK"}, "outcome"),
        ({"decision_id": "someone-else"}, "decision_id"),
    ):
        report = verify_receipts(records, [{**good[0], **wrong}], read_verdict)
        assert not report.ok and report.mismatched[cid] == [field]
    report = verify_receipts(records, [{"correlation_id": "nobody/prop-9"}], read_verdict)
    assert report.unknown == ["nobody/prop-9"] and not report.ok
    # A record changed after the run no longer gives its own action_ref.
    changed = [{**first, "arguments": {"setpoint_c": 99.0}}, *records[1:]]
    assert cid in verify_receipts(changed, good, read_verdict).unbound_records


@pytest.mark.req("ADC-INT-003")
def test_time_is_given_as_utc_from_a_fixed_epoch() -> None:
    assert utc(0) == "2026-01-01T00:00:00.000Z"
    assert utc(90_061_001) == "2026-01-02T01:01:01.001Z"
    assert utc(1_000, "2030-06-01T12:00:00Z") == "2030-06-01T12:00:01.000Z"
    with pytest.raises(HttpGateConfigError, match="ADC_GATE_EPOCH"):
        command_from_environment({"ADC_GATE_COMMAND": "true", "ADC_GATE_EPOCH": "yesterday"})
    gate = Captured(epoch="2030-06-01T12:00:00Z")
    _run(gate, 600)
    body = next(b for p, b in gate.sent if p == "/evaluate")
    assert body["correlation"]["issued_at"].startswith("2030-06-01T12:")
    assert body["correlation"]["time_anchor"] == "2030-06-01T12:00:00Z"


@pytest.mark.req("ADC-INT-004")
def test_a_sample_of_the_plant_is_sent_only_when_asked_for() -> None:
    plain = Captured()
    _run(plain, 600)
    assert all("context" not in b for p, b in plain.sent if p == "/evaluate")
    asked = Captured(wants_context=True)
    _run(asked, 600)
    context = next(b for p, b in asked.sent if p == "/evaluate")["context"]
    assert context["read_only"] is True and context["schema"] == "agentic_datacenter.context/1"
    assert context["observed_at"] == utc(context["time_ms"])
    for group in ("temperatures", "load", "interlocks"):
        assert context[group], group
        for point in context[group]:
            assert set(point) == {"tag", "value", "unit", "quality", "time_ms", "observed_at"}
    assert any(p["tag"].endswith(".supply_air_c") and p["unit"] for p in context["temperatures"])
    assert any(p["tag"].endswith(".alarm_lockout") for p in context["interlocks"])
    assert context["redundancy"] and isinstance(context["alarms"], list)
    assert context["permits"] == {"modelled": False, "items": []}
    assert command_from_environment(
        {"ADC_GATE_COMMAND": "true", "ADC_GATE_CONTEXT": "1"}
    ).wants_context


@pytest.mark.req("ADC-INT-005")
def test_the_state_and_the_run_do_not_depend_on_the_session() -> None:
    one, two = _run(Captured()), _run(Captured())
    assert one.state_hashes == two.state_hashes
    sessions = {r["gate_detail"]["session"] for r in one.records + two.records}
    assert len(sessions) == 2
    strip = [[{k: v for k, v in r.items() if k != "gate_detail"} for r in x.records]
             for x in (one, two)]  # fmt: skip
    assert strip[0] == strip[1]


@pytest.mark.req("ADC-INT-001")
def test_a_receipt_the_service_gives_is_kept_up_to_a_size() -> None:
    kept = _run(Captured(answer={"receipt": {"sig": "abc", "alg": "ed25519"}})).records[0]
    assert kept["gate_detail"]["service_receipt"] == {"sig": "abc", "alg": "ed25519"}
    big = {"blob": "x" * (MAX_RECEIPT_BYTES + 1)}
    dropped = _run(Captured(answer={"receipt": big})).records[0]
    assert "service_receipt" not in dropped["gate_detail"]


@pytest.mark.req("ADC-INT-006")
def test_the_example_adapter_writes_receipts_that_verify(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    receipts = tmp_path / "receipts.jsonl"
    monkeypatch.chdir(REPO)
    monkeypatch.setenv("ADC_GATE_COMMAND", shlex.join([sys.executable, str(ADAPTER)]))
    monkeypatch.setenv("ADC_GATE_NAME", "example_command")
    monkeypatch.setenv("ADC_GATE_CONTEXT", "1")
    monkeypatch.setenv("ADC_RECEIPTS_FILE", str(receipts))
    bundle = tmp_path / "bundle"
    assert (
        scenario_cli(
            ["run", "OP-03", "--gate", "command_gate", "--seconds", "900", "--out", str(bundle)]
        )
        == 0
    )
    lines = [json.loads(t) for t in receipts.read_text().splitlines()]
    assert {"action_ref", "verdict", "decision_id"} <= set(lines[0])
    assert any("outcome" in line for line in lines)
    capsys.readouterr()
    assert gate_cli(["verify-receipts", str(bundle), str(receipts), "--require-all"]) == 0
    report = json.loads(capsys.readouterr().out)
    assert report["ok"] and report["matched"]
    lines[0]["verdict"] = "DENY" if lines[0]["verdict"] != "DENY" else "ALLOW"
    receipts.write_text("".join(json.dumps(line) + "\n" for line in lines))
    assert gate_cli(["verify-receipts", str(bundle), str(receipts)]) == 1


@pytest.mark.req("ADC-INT-006")
def test_receipts_without_a_served_gate_are_not_reported_as_checked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bundle = tmp_path / "bundle"
    assert scenario_cli(
        ["run", "OP-03", "--seconds", "600", "--out", str(bundle),
         "--profile", str(REPO / "profiles/generic_dc.yaml"),
         "--contracts", str(REPO / "contracts")]
    ) in (0, 1)  # fmt: skip
    empty = tmp_path / "none.jsonl"
    empty.write_text("")
    assert gate_cli(["verify-receipts", str(bundle), str(empty)]) == 1
    assert "carries a correlation_id" in capsys.readouterr().err


@pytest.mark.req("ADC-INT-001")
def test_the_wire_schema_describes_what_is_sent() -> None:
    schema = json.loads((REPO / "docs/reference/gate-http-v1.schema.json").read_text())
    defs = schema["$defs"]
    gate = Captured(wants_context=True)
    _run(gate, 600)
    body = next(b for p, b in gate.sent if p == "/evaluate")
    assert set(body["correlation"]) == set(defs["correlation"]["required"])
    assert set(body["context"]) == set(defs["context"]["required"])
    assert "context" not in defs["evaluate_request"]["required"]
    outcome = next(b for p, b in gate.sent if p == "/outcome")
    assert set(outcome) == set(defs["outcome_request"]["required"])
    assert "receipt" in defs["evaluate_answer"]["properties"]
    assert "receipt" not in defs["evaluate_answer"]["required"]
