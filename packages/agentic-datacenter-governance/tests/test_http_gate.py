"""ADC-GOV-008: a gate served over HTTP is driven like any other, and fails closed."""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from collections.abc import Callable, Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from agentic_datacenter.governance.bindings.http_gate import (
    SCHEMA,
    VERDICT_ALIASES,
    CommandGate,
    HttpGate,
    HttpGateConfigError,
    command_from_environment,
    from_environment,
    read_verdict,
)
from agentic_datacenter.governance.conformance import check_gate
from agentic_datacenter.governance.gate import (
    AuthenticatedActor,
    BoundedWrite,
    Outcome,
    PremiseResult,
    PremiseSnapshot,
    Proposal,
    Verdict,
)

REPO = Path(__file__).resolve().parents[3]
ACTOR = AuthenticatedActor("agent", "test")
WRITE = BoundedWrite("cooling.chw_plant[CHW].chws_sp_c", 18.5, 18.0)
CLEAN = PremiseSnapshot(
    time_ms=5000, contract_known=True, risk_tier="R1", approval="none", writes=(WRITE,),
    premises=(PremiseResult("all(pod.supply_air_c <= 25.0)", True, "holds"),),
    rollback_available=True,
)  # fmt: skip
PROPOSAL = Proposal("prop-1", "chw.set_supply_setpoint.v1", {"setpoint_c": 18.5})


def _load(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _serve(handler: type[BaseHTTPRequestHandler]) -> Iterator[str]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()


def _answering(answer: Callable[[dict[str, Any]], Any]) -> type[BaseHTTPRequestHandler]:
    seen: list[dict[str, Any]] = []

    class Handler(BaseHTTPRequestHandler):
        requests = seen

        def do_POST(self) -> None:  # noqa: N802
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append({"path": self.path, **body})
            data = json.dumps(answer(body)).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass

    return Handler


@pytest.fixture
def example_url() -> Iterator[str]:
    server = _load(REPO / "examples/http-gate/server.py", "example_http_gate_server")
    yield from _serve(server.Handler)


@pytest.mark.req("ADC-GOV-008")
@pytest.mark.req("ADC-GOV-004")
def test_the_example_service_passes_the_gate_interface_suite_through_the_binding(
    example_url: str,
) -> None:
    check_gate(lambda: HttpGate(example_url, name="example"))


@pytest.mark.req("ADC-GOV-008")
def test_request_carries_what_the_binding_established_and_outcomes_are_reported() -> None:
    handler = _answering(lambda body: {"schema": SCHEMA, "verdict": "ALLOW", "reasons": ["ok"]})
    for url in _serve(handler):
        gate = HttpGate(url)
        decision = gate.evaluate(PROPOSAL, CLEAN, ACTOR)
        gate.record_outcome(decision.decision_ref, Outcome("APPLIED", "read back"))
    evaluate, outcome = handler.requests  # type: ignore[attr-defined]
    assert evaluate["path"] == "/evaluate" and evaluate["schema"] == SCHEMA
    assert evaluate["premises"]["writes"] == [{"tag": WRITE.tag, "value": 18.5, "previous": 18.0}]
    assert evaluate["premises"]["time_ms"] == 5000
    assert evaluate["actor"] == {"principal": "agent", "credential": "test"}
    assert outcome == {
        "path": "/outcome", "schema": SCHEMA, "session": gate.session,
        "decision_ref": decision.decision_ref, "status": "APPLIED", "detail": "read back",
    }  # fmt: skip
    assert evaluate["session"] == gate.session
    assert evaluate["tool_call"] == {
        "name": PROPOSAL.contract_id, "arguments": {"setpoint_c": 18.5},
        "writes": [{"tag": WRITE.tag, "value": 18.5}],
    }  # fmt: skip
    assert decision.verdict is Verdict.ALLOW and decision.bounded_writes == (WRITE,)
    assert decision.expires_at_ms > CLEAN.time_ms and decision.single_use_nonce


@pytest.mark.req("ADC-GOV-008")
def test_the_service_cannot_widen_what_an_allow_authorizes() -> None:
    def answer(body: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": SCHEMA, "verdict": "ALLOW", "reasons": ["ok"],
            "bounded_writes": [{"tag": "electrical.mv_switchgear[MV].cb_open", "value": True}],
            "decision_ref": "mine", "expires_at_ms": 10**12,
        }  # fmt: skip

    for url in _serve(_answering(answer)):
        decision = HttpGate(url).evaluate(PROPOSAL, CLEAN, ACTOR)
    assert decision.bounded_writes == (WRITE,)
    assert decision.decision_ref.startswith("dec-")
    assert decision.expires_at_ms == CLEAN.time_ms + 30_000


@pytest.mark.req("ADC-GOV-008")
@pytest.mark.parametrize(
    "answer",
    [
        {"verdict": "ALLOW", "reasons": ["no schema"]},
        {"schema": SCHEMA, "verdict": "MAYBE", "reasons": ["bad verdict"]},
        {
            "schema": SCHEMA,
            "verdict": "allow_with_caps",
            "reasons": ["conditions Agentic-Datacenter cannot hold"],
        },
        {"schema": SCHEMA, "verdict": "ALLOW", "reasons": []},
        ["not", "an", "object"],
    ],
)
def test_an_answer_that_is_not_a_valid_verdict_abstains(answer: Any) -> None:
    for url in _serve(_answering(lambda body: answer)):
        decision = HttpGate(url).evaluate(PROPOSAL, CLEAN, ACTOR)
    assert decision.verdict is Verdict.ABSTAIN
    assert decision.bounded_writes == ()


@pytest.mark.req("ADC-GOV-008")
def test_a_service_that_does_not_answer_abstains() -> None:
    for served in _serve(_answering(lambda body: {})):
        url = served  # the server is shut down; nothing listens on the port any more
    gate = HttpGate(url, timeout_s=2)
    decision = gate.evaluate(PROPOSAL, CLEAN, ACTOR)
    assert decision.verdict is Verdict.ABSTAIN
    assert decision.reasons[0].startswith("gate service did not answer")
    gate.record_outcome(decision.decision_ref, Outcome("NOT_EXECUTED"))


@pytest.mark.req("ADC-GOV-008")
def test_an_address_outside_loopback_needs_consent() -> None:
    with pytest.raises(HttpGateConfigError):
        HttpGate("http://gate.example.org:8787")
    HttpGate("http://gate.example.org:8787", allow_remote=True)
    with pytest.raises(HttpGateConfigError):
        from_environment({})
    with pytest.raises(HttpGateConfigError):
        from_environment({"ADC_GATE_URL": "http://127.0.0.1:1", "ADC_GATE_PROFILE": "GOVERNED"})
    gate = from_environment({"ADC_GATE_URL": "http://[::1]:1", "ADC_GATE_NAME": "theirs"})
    assert (gate.name, gate.profile) == ("theirs", "DECISION_ONLY")


@pytest.mark.req("ADC-GOV-004")
def test_the_python_template_passes_the_gate_interface_suite() -> None:
    template = _load(REPO / "examples/python-gate/src/example_gate/__init__.py", "example_gate")
    check_gate(template.ExampleGate)
    assert template.create(None).profile == "DECISION_ONLY"


@pytest.mark.req("ADC-GOV-008")
def test_the_published_schema_matches_what_the_binding_sends_and_reads() -> None:
    from agentic_datacenter.governance.bindings.http_gate import request_body
    from agentic_datacenter.governance.gate import OUTCOMES

    schema = json.loads((REPO / "docs/reference/gate-http-v1.schema.json").read_text())
    assert schema["$id"] == SCHEMA
    defs = schema["$defs"]
    body = request_body(PROPOSAL, CLEAN, ACTOR)
    assert set(body) == set(defs["evaluate_request"]["required"])
    for part in ("proposal", "premises", "actor"):
        spec = defs["evaluate_request"]["properties"][part]
        assert set(body[part]) == set(spec["required"]) == set(spec["properties"])  # type: ignore[arg-type]
    aliases = {word: verdict.value for word, verdict in VERDICT_ALIASES.items()}
    assert defs["verdict_aliases"]["const"] == aliases
    assert defs["outcome_request"]["properties"]["status"]["enum"] == list(OUTCOMES)
    assert set(defs["outcome_request"]["required"]) == set(defs["outcome_request"]["properties"])


@pytest.mark.req("ADC-GOV-008")
@pytest.mark.parametrize(
    ("word", "verdict"),
    [
        ("permit", Verdict.ALLOW), ("Admitted", Verdict.ALLOW), ("block", Verdict.DENY),
        ("forbid", Verdict.DENY), ("ask", Verdict.VERIFY), ("require-approval", Verdict.VERIFY),
        ("ESCALATE", Verdict.VERIFY), ("skip", Verdict.ABSTAIN), ("out of scope", Verdict.ABSTAIN),
        ("VERIFY", Verdict.VERIFY), ("defer", None), ("modify", None),
    ],
)  # fmt: skip
def test_a_service_may_answer_in_its_own_words(word: str, verdict: Verdict | None) -> None:
    assert read_verdict(word) is verdict


@pytest.mark.req("ADC-GOV-008")
def test_an_own_word_is_read_and_kept_on_the_decision() -> None:
    handler = _answering(lambda body: {"schema": SCHEMA, "verdict": "block", "reasons": ["no"]})
    for url in _serve(handler):
        decision = HttpGate(url).evaluate(PROPOSAL, CLEAN, ACTOR)
    assert decision.verdict is Verdict.DENY
    assert dict(decision.detail)["service_verdict"] == "block"


@pytest.mark.req("ADC-GOV-008")
def test_a_stateful_service_gets_a_session_per_gate_and_is_not_restored() -> None:
    env = {"ADC_GATE_URL": "http://127.0.0.1:1"}
    one, two = from_environment(env), from_environment(env)
    assert one.session != two.session and one.restorable
    assert not from_environment({**env, "ADC_GATE_STATEFUL": "1"}).restorable


def _command(tmp_path: Path, body: str) -> str:
    script = tmp_path / "hook.py"
    script.write_text("import json, sys\nmessage = json.load(sys.stdin)\n" + body)
    return f"{sys.executable} {script}"


@pytest.mark.req("ADC-GOV-008")
@pytest.mark.req("ADC-GOV-004")
def test_a_command_gate_is_driven_over_standard_input_and_output(tmp_path: Path) -> None:
    command = _command(tmp_path, (
        "request = message['request']\n"
        "if message['endpoint'] == '/evaluate':\n"
        "    p = request['premises']\n"
        "    bad = p['schema_errors'] or not p['contract_known'] or "
        "any(x['holds'] is not True for x in p['premises'])\n"
        "    print(json.dumps({'schema': request['schema'], "
        "'verdict': 'deny' if bad else 'allow', 'reasons': ['hook']}))\n"
    ))  # fmt: skip
    gate = command_from_environment({"ADC_GATE_COMMAND": command, "ADC_GATE_NAME": "hook"})
    check_gate(lambda: CommandGate(command, name="hook"))
    decision = gate.evaluate(PROPOSAL, CLEAN, ACTOR)
    assert decision.verdict is Verdict.ALLOW and decision.bounded_writes == (WRITE,)
    gate.record_outcome(decision.decision_ref, Outcome("APPLIED"))


@pytest.mark.req("ADC-GOV-008")
def test_a_command_that_exits_2_denies_and_one_that_fails_abstains(tmp_path: Path) -> None:
    refusing = _command(tmp_path, "print('not allowed here', file=sys.stderr)\nsys.exit(2)\n")
    decision = CommandGate(refusing).evaluate(PROPOSAL, CLEAN, ACTOR)
    assert decision.verdict is Verdict.DENY and decision.reasons[0] == "not allowed here"
    failing = _command(tmp_path, "sys.exit(1)\n")
    assert CommandGate(failing).evaluate(PROPOSAL, CLEAN, ACTOR).verdict is Verdict.ABSTAIN
    with pytest.raises(HttpGateConfigError):
        command_from_environment({})


def test_the_example_package_asks_for_as_many_people_as_the_contract_does() -> None:
    """It asked for one person whatever the contract said, so work that needs two was
    executed on one approval (AD-14 at full length)."""
    from dataclasses import replace

    template = _load(REPO / "examples/python-gate/src/example_gate/__init__.py", "example_gate")
    gate = template.create(None)
    for approval, people in (("one_operator", 1), ("two_person", 2)):
        asked = gate.evaluate(PROPOSAL, replace(CLEAN, risk_tier="R2", approval=approval), ACTOR)
        assert asked.verdict is Verdict.VERIFY and asked.required_approvers == people
def _status(code: int, headers: dict[str, str], body: bytes) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(code)
            for name, value in {**headers, "Content-Length": str(len(body))}.items():
                self.send_header(name, value)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
            pass

    return Handler


@pytest.mark.req("ADC-GOV-008")
def test_a_proxy_in_the_environment_never_sees_what_is_meant_for_loopback(
    example_url: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    proxied: list[str] = []
    for proxy in _serve(_answering(lambda body: proxied.append("seen") or {})):
        for name in ("http_proxy", "HTTP_PROXY", "https_proxy", "HTTPS_PROXY"):
            monkeypatch.setenv(name, proxy)
        monkeypatch.delenv("no_proxy", raising=False)
        monkeypatch.delenv("NO_PROXY", raising=False)
        decision = HttpGate(example_url).evaluate(PROPOSAL, CLEAN, ACTOR)
    assert proxied == []
    assert decision.verdict is not Verdict.ABSTAIN


@pytest.mark.req("ADC-GOV-008")
def test_a_redirect_is_not_followed() -> None:
    elsewhere: list[str] = []
    for target in _serve(_answering(lambda body: elsewhere.append("seen") or {})):
        moved = _status(307, {"Location": target + "/evaluate"}, b"")
        for url in _serve(moved):
            gate = HttpGate(url)
            decision = gate.evaluate(PROPOSAL, CLEAN, ACTOR)
    assert elsewhere == []
    assert decision.verdict is Verdict.ABSTAIN and gate.failures


@pytest.mark.req("ADC-GOV-008")
def test_an_answer_too_long_to_read_abstains() -> None:
    huge = b'{"pad": "' + b"x" * (1 << 20) + b'"}'
    for url in _serve(_status(200, {"Content-Type": "application/json"}, huge)):
        gate = HttpGate(url)
        decision = gate.evaluate(PROPOSAL, CLEAN, ACTOR)
    assert decision.verdict is Verdict.ABSTAIN
    assert "longer than" in decision.reasons[0] and len(gate.failures) == 1


@pytest.mark.req("ADC-GOV-008")
def test_a_failed_call_is_kept_on_the_gate_and_a_good_one_is_not(example_url: str) -> None:
    gate = HttpGate(example_url)
    gate.evaluate(PROPOSAL, CLEAN, ACTOR)
    assert gate.failures == []
