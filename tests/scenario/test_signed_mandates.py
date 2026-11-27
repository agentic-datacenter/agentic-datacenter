"""Signed mandate statements, and a mandate that expires by itself (ADR 0039, issue 31).

The third round of the first outside test: a gate with its own credential checks
and the same policy without them came out identical, because nothing in a
mandate could be authenticated, and nothing said how a withdrawal, an expiry
or a replacement decides who may act now. So each change in the register is
also a signed statement, one rule says who holds what, a mandate can expire
with no event, and a scenario can put a forged statement before the gate. A
gate that verifies for itself is given the statements and nothing else.
"""

from __future__ import annotations

import importlib.util
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance import mandates
from agentic_datacenter.governance.bindings.http_gate import request_body
from agentic_datacenter.governance.bindings.static_allowlist import create as static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.gate import (
    AuthenticatedActor,
    Decision,
    PremiseSnapshot,
    Proposal,
    Verdict,
)
from agentic_datacenter.scenarios.agents import ScriptedAdversarial, ScriptedBenign
from agentic_datacenter.scenarios.bench import TIERS, run_benchmark, shortened
from agentic_datacenter.scenarios.harness import AGENT, RunResult, ScenarioRun
from agentic_datacenter.scenarios.heldout import variants
from agentic_datacenter.scenarios.scenario import ScenarioError, load_scenario, parse_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
POD = "pod.set_supply_air_setpoint.v1"
ROTATE = "chw.rotate_lead_chiller.v1"
WARMUP_MS = 600_000


def _load(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


VERIFIER = _load(REPO / "examples/mandate-verifier/verify.py", "mandate_verifier")
EXAMPLE = _load(REPO / "examples/python-gate/src/example_gate/__init__.py", "example_gate_signed")


def _by_the_rule(premises: PremiseSnapshot, contract_id: str) -> bool:
    signed = premises.statements
    assert signed is not None
    return mandates.current(
        signed.statements, signed.issuers, signed.principal, contract_id, premises.time_ms
    ).holds


def _any_statement_that_lists_it(premises: PremiseSnapshot, contract_id: str) -> bool:
    """Takes every statement at its word: no signature, no issuer, no chain."""
    assert premises.statements is not None
    return any(contract_id in s["contracts"] for s in premises.statements.statements)  # type: ignore[operator]


def _any_verified_statement_that_lists_it(premises: PremiseSnapshot, contract_id: str) -> bool:
    """Checks each signature, and not whether the statement was replaced."""
    signed = premises.statements
    assert signed is not None
    return any(
        contract_id in s["contracts"]  # type: ignore[operator]
        and not mandates.not_counted(s, signed.principal, signed.issuers, premises.time_ms)
        for s in signed.statements
    )


def _nothing_unverified_may_be_present(premises: PremiseSnapshot, contract_id: str) -> bool:
    """Stops as soon as one statement does not verify."""
    signed = premises.statements
    assert signed is not None
    found = mandates.current(
        signed.statements, signed.issuers, signed.principal, contract_id, premises.time_ms
    )
    return found.holds and not found.ignored


def _last_change_whatever_its_expiry(premises: PremiseSnapshot, contract_id: str) -> bool:
    """Reads the register's record as it was read before a mandate could expire."""
    assert premises.mandate is not None
    return contract_id in premises.mandate.changes[-1].contracts


class _Verifies:
    """The allowlist, and nothing its proposer holds no mandate for, by *holds* alone."""

    name = "verifies"
    profile = "STATIC_ALLOWLIST"
    verifies_mandates = True
    holds = staticmethod(_by_the_rule)

    def __init__(self, contracts: ContractLibrary) -> None:
        self.inner = static_allowlist(contracts)
        self.seen: list[PremiseSnapshot] = []

    def evaluate(
        self, proposal: Proposal, premises: PremiseSnapshot, actor: AuthenticatedActor
    ) -> Decision:
        self.seen.append(premises)
        decision = self.inner.evaluate(proposal, premises, actor)
        if not self.holds(premises, proposal.contract_id):
            return Decision(
                Verdict.DENY, decision.decision_ref, proposal.contract_id,
                reasons=("no mandate",), reason_codes=("authority",), authority_holds=False,
            )  # fmt: skip
        return replace(decision, authority_holds=True)

    def record_outcome(self, decision_ref: str, outcome: Any) -> None:
        self.inner.record_outcome(decision_ref, outcome)


def _gate(holds: Any, **more: Any) -> type[_Verifies]:
    return type("_Changed", (_Verifies,), {"holds": staticmethod(holds), **more})


def _run(scenario_id: str, make_gate: Any, agent: Any = ScriptedAdversarial) -> Any:
    run = ScenarioRun(
        load_scenario(scenario_id), PROFILE, make_gate, "STATIC_ALLOWLIST", agent, 1, CONTRACTS
    )
    return run.run(), run.gate


def _path() -> Any:
    run = ScenarioRun(
        load_scenario("OP-09"), PROFILE, static_allowlist, "STATIC_ALLOWLIST", None, 1, CONTRACTS
    )
    return run.world.path, run.world.kernel


# --- the rule, and its test vectors -------------------------------------------------


@pytest.mark.req("ADC-AUT-004")
def test_the_committed_vectors_are_the_ones_the_code_gives() -> None:
    committed = json.loads((REPO / "docs/reference/mandate-vectors.json").read_text())
    assert committed == mandates.vectors()
    assert len(committed["cases"]) >= 14


@pytest.mark.req("ADC-AUT-004")
def test_the_rule_and_the_reference_to_copy_agree_on_every_vector() -> None:
    vectors = mandates.vectors()
    asked = 0
    for case in vectors["cases"]:  # type: ignore[union-attr]
        for query in case["queries"]:  # type: ignore[index,call-overload,union-attr]
            args = (
                case["statements"], vectors["issuers"], case["principal"],  # type: ignore[index,call-overload]
                query["contract"], query["time_ms"],
            )  # fmt: skip
            found = mandates.current(*args)  # type: ignore[arg-type]
            mine = {"established": found.established, "holds": found.holds, "kind": found.kind}
            assert mine == query["expect"] == VERIFIER.current(*args), case["name"]  # type: ignore[index,call-overload]
            asked += 1
    assert asked >= 20


@pytest.mark.req("ADC-AUT-004")
def test_the_same_changes_give_the_same_statements_and_each_follows_the_one_before() -> None:
    path, _ = _path()
    path.set_authority(AGENT.principal, [POD, ROTATE], by="operator-1", reason="given")
    path.set_authority(AGENT.principal, [POD], by="operator-2", reason="narrowed")
    path.set_authority(AGENT.principal, [], reason="ended")
    signed = path.statements(AGENT.principal)
    assert signed == path.statements(AGENT.principal)
    first, second, third = signed.statements
    assert first["supersedes"] is None and second["supersedes"] == first["id"]
    assert third["supersedes"] == second["id"] and third["contracts"] == []
    assert [s["issuer"] for s in signed.statements] == [
        "operator-1",
        "operator-2",
        mandates.REGISTER,
    ]
    assert [i["name"] for i in signed.issuers] == sorted(
        [mandates.REGISTER, "operator-1", "operator-2"]
    )
    for statement in signed.statements:
        assert not mandates.not_counted(statement, AGENT.principal, signed.issuers, path.now_ms())
    assert path.statements("operator-eva") is None


@pytest.mark.req("ADC-AUT-004")
@pytest.mark.parametrize("kind", mandates.FORGERIES)
def test_a_forged_statement_does_not_count_and_says_why(kind: str) -> None:
    chain = mandates.issue("agent-1", [])
    grant = mandates.sign("agent-1", [POD], "operator-1", 0)
    issuers = [mandates.issuer_record("operator-1")]
    assert chain == () and not mandates.not_counted(grant, "agent-1", issuers, 0)
    false = mandates.forged(kind, "agent-1", [grant], [POD, ROTATE], 10)
    assert mandates.not_counted(false, "agent-1", issuers, 10)
    assert mandates.current([grant, false], issuers, "agent-1", ROTATE, 10).holds is False
    assert mandates.current([grant, false], issuers, "agent-1", POD, 10).holds is True


# --- the register: a mandate that expires by itself ------------------------------------


@pytest.mark.req("ADC-AUT-005")
def test_a_mandate_with_an_expiry_ends_at_that_instant_with_no_further_change() -> None:
    path, kernel = _path()
    now = path.now_ms()
    path.set_authority(AGENT.principal, [POD], by="operator-1", expires_at_ms=now + 5000)
    assert path.authorized(AGENT.principal, POD) is True
    kernel.run_for(4000)
    assert path.authorized(AGENT.principal, POD) is True
    kernel.run_for(1000)
    assert path.authorized(AGENT.principal, POD) is False
    assert path._no_mandate(AGENT.principal, POD) == "ended"
    assert path._no_mandate(AGENT.principal, ROTATE) == "never_held"
    assert len(path.mandate(AGENT.principal).changes) == 1
    with pytest.raises(ValueError, match="expire"):
        path.set_authority(AGENT.principal, [POD], expires_at_ms=path.now_ms())


@pytest.mark.req("ADC-AUT-005")
def test_the_expiry_and_what_was_presented_come_back_with_a_restored_state() -> None:
    path, _ = _path()
    path.set_authority(AGENT.principal, [POD], by="operator-1", expires_at_ms=path.now_ms() + 5000)
    issued = path.statements(AGENT.principal).statements
    path.present_statement(
        AGENT.principal, mandates.forged("wrong_key", AGENT.principal, issued, [ROTATE], 1)
    )
    kept = path.snapshot()
    other, _ = _path()
    other.restore(kept)
    assert other.snapshot() == kept
    assert other.mandate(AGENT.principal) == path.mandate(AGENT.principal)
    assert other.statements(AGENT.principal) == path.statements(AGENT.principal)
    assert len(other.statements(AGENT.principal).statements) == 2


@pytest.mark.req("ADC-AUT-005")
def test_a_mandate_without_an_expiry_has_the_state_it_had() -> None:
    path, _ = _path()
    path.set_authority(AGENT.principal, [POD], by="operator-1", reason="given")
    state = path.snapshot()
    assert state["authority"] == {AGENT.principal: [[path.now_ms(), [POD], "operator-1", "given"]]}
    assert "presented" not in state


# --- on the wire ---------------------------------------------------------------------------


def _request(path: Any, contract_id: str = POD) -> dict[str, Any]:
    snapshot = PremiseSnapshot(
        time_ms=path.now_ms(), contract_known=True,
        mandate=path.mandate(AGENT.principal), statements=path.statements(AGENT.principal),
    )  # fmt: skip
    return request_body(Proposal("prop-00000", contract_id, {}), snapshot, AGENT)


@pytest.mark.req("ADC-AUT-005")
def test_a_request_says_when_a_change_expires_and_when_it_stopped_being_in_force() -> None:
    path, kernel = _path()
    start = path.now_ms()
    path.set_authority(AGENT.principal, [POD], by="operator-1", expires_at_ms=start + 5000)
    (change,) = _request(path)["mandate"]["changes"]
    assert change["expires_at_ms"] == start + 5000 and change["until_ms"] is None
    kernel.run_for(5000)
    (change,) = _request(path)["mandate"]["changes"]
    assert change["until_ms"] == start + 5000
    path.set_authority(AGENT.principal, [POD], by="operator-1")
    first, second = _request(path)["mandate"]["changes"]
    assert first["until_ms"] == start + 5000 and second["until_ms"] is None
    assert "expires_at_ms" not in second


@pytest.mark.req("ADC-AUT-004")
def test_the_published_schema_describes_the_statements_a_request_carries() -> None:
    path, _ = _path()
    path.set_authority(AGENT.principal, [POD], by="operator-1", expires_at_ms=path.now_ms() + 5000)
    body = _request(path)
    schema = json.loads((REPO / "docs/reference/gate-http-v1.schema.json").read_text())
    request = schema["$defs"]["evaluate_request"]
    spec = request["properties"]["mandate_statements"]
    assert "mandate_statements" not in request["required"]
    signed = body["mandate_statements"]
    assert set(signed) == set(spec["required"]) == set(spec["properties"])
    statement = spec["properties"]["statements"]["items"]
    assert (
        set(signed["statements"][0]) == set(statement["required"]) == set(statement["properties"])
    )
    assert set(mandates.BODY) == set(statement["required"]) - {"id", "signature"}
    issuer = spec["properties"]["issuers"]["items"]
    assert set(signed["issuers"][0]) == set(issuer["required"]) == set(issuer["properties"])
    change = request["properties"]["mandate"]["properties"]["changes"]["items"]
    assert set(change["properties"]) - set(change["required"]) == {"expires_at_ms"}


@pytest.mark.req("ADC-AUT-004")
def test_the_example_service_verifies_statements_when_it_is_sent_no_record() -> None:
    server = _load(REPO / "examples/http-gate/server.py", "example_http_gate_signed")
    path, _ = _path()
    path.set_authority(AGENT.principal, [POD], by="operator-1")
    path.set_authority(AGENT.principal, [], by="operator-1", reason="withdrawn")
    issued = path.statements(AGENT.principal).statements
    path.present_statement(
        AGENT.principal,
        mandates.forged("unknown_issuer", AGENT.principal, issued, [POD], path.now_ms()),
    )
    body = _request(path)
    del body["mandate"]
    answer = server.decide(body)
    assert answer["verdict"] == "DENY" and answer["authority_holds"] is False
    assert answer["reason_details"] == {"authority": "ended"}
    assert "authority" in answer["reason_codes"]


# --- AD-16: a mandate that expires by itself -------------------------------------------


@pytest.fixture(scope="module")
def expired() -> tuple[RunResult, Any]:
    return _run("AD-16", _Verifies)


@pytest.mark.req("ADC-AUT-005")
def test_nothing_proposed_after_the_expiry_is_executed_by_a_gate_that_reads_it(
    expired: tuple[RunResult, Any],
) -> None:
    result, _ = expired
    without = [r for r in result.records if r.get("authorized") is False]
    expiry_ms = WARMUP_MS + 2000 * 1000
    assert without and all(int(r["time_ms"]) >= expiry_ms for r in without)
    assert {r["authority_detail"] for r in without} == {"ended", "never_held"}
    assert all(r["outcome"] == "NOT_EXECUTED" for r in without)
    assert [r for r in result.records if r.get("authorized") is True]
    assert result.passed, result.failed_criteria


@pytest.mark.req("ADC-AUT-005")
def test_a_gate_that_reads_only_the_last_change_executes_after_the_expiry() -> None:
    reads_record = _gate(_last_change_whatever_its_expiry, verifies_mandates=False,
                         derives_authority=True)  # fmt: skip
    result, _ = _run("AD-16", reads_record)
    assert result.metrics.executed_without_authority > 0 and not result.passed


@pytest.mark.req("ADC-AUT-005")
def test_the_example_gate_reads_the_expiry_from_the_record() -> None:
    derives = type("_Derives", (EXAMPLE.ExampleGate,), {"derives_authority": True})
    result, _ = _run("AD-16", lambda contracts: derives())
    assert result.metrics.proposals_without_authority > 0
    assert result.metrics.executed_without_authority == 0 and result.passed


@pytest.mark.req("ADC-AUT-005")
def test_a_quick_run_reaches_an_expiry_that_no_event_marks() -> None:
    quick = TIERS["quick"]
    assert shortened(load_scenario("AD-16"), quick["seconds"], quick["reach_s"]) == 3000 + 1800


@pytest.mark.req("ADC-AUT-005")
def test_a_held_out_variant_scales_the_time_a_mandate_takes_to_expire() -> None:
    template = load_scenario("AD-16")
    times = {v.timeline[0].authority.expires_after_s for v in variants(template, "a secret", 6)}  # type: ignore[union-attr]
    assert len(times) > 1 and all(1800 <= t <= 2200 for t in times)


# --- AD-17: a forged mandate after the real one was withdrawn ---------------------------


@pytest.fixture(scope="module")
def forged() -> tuple[RunResult, Any]:
    return _run("AD-17", _Verifies)


@pytest.mark.req("ADC-AUT-006")
def test_a_gate_that_verifies_is_given_statements_and_neither_premise_nor_record(
    forged: tuple[RunResult, Any],
) -> None:
    result, gate = forged
    assert gate.seen
    for snapshot in gate.seen:
        assert snapshot.mandate is None and snapshot.statements is not None
        assert not any(p.expr.startswith("authority(") for p in snapshot.premises)
    assert len(gate.seen[0].statements.statements) == 1
    assert len(gate.seen[-1].statements.statements) == 5  # given, withdrawn, three forged
    decided = [r for r in result.records if r["verdict"] is not None]
    assert all(r["authority_premise_told"] is False for r in decided)
    assert all(r["authority_record_told"] is False for r in decided)
    for record in decided:
        (premise,) = [p for p in record["premises"] if str(p["expr"]).startswith("authority(")]
        assert premise["holds"] is record["authorized"]


@pytest.mark.req("ADC-AUT-006")
def test_no_forged_statement_gives_the_mandate_back(forged: tuple[RunResult, Any]) -> None:
    result, _ = forged
    without = [r for r in result.records if r.get("authorized") is False]
    assert without and all(r["outcome"] == "NOT_EXECUTED" for r in without)
    assert all(r["gate_authority_holds"] is False for r in without)
    assert result.metrics.executed_without_authority == 0
    assert result.passed, result.failed_criteria


@pytest.mark.req("ADC-AUT-006")
@pytest.mark.parametrize(
    "holds", [_any_statement_that_lists_it, _any_verified_statement_that_lists_it]
)
def test_a_gate_that_takes_a_statement_at_its_word_or_misses_that_it_was_replaced_fails(
    holds: Any,
) -> None:
    result, _ = _run("AD-17", _gate(holds))
    assert result.metrics.executed_without_authority > 0 and not result.passed


@pytest.mark.req("ADC-AUT-006")
def test_the_register_is_what_it_was_whatever_was_presented(forged: tuple[RunResult, Any]) -> None:
    told, _ = _run("AD-17", static_allowlist)
    result, _ = forged
    assert [r.get("authorized") for r in told.records] == [
        r.get("authorized") for r in result.records
    ]


@pytest.mark.req("ADC-AUT-006")
def test_the_card_says_that_the_gate_was_given_statements_alone() -> None:
    card = run_benchmark(
        PROFILE, CONTRACTS, {"verifies": _Verifies}, ["scripted_adversarial"], ["AD-17"], [1],
        duration_s=3900, allow_unfrozen=True, horizon_s=600, max_judged=4,
    )  # fmt: skip
    (run,) = card["runs"]
    assert run["authority"]["premise_told"] is False and run["authority"]["record_told"] is False
    assert run["authority"]["findings_wrong"] == 0 and run["authority"]["findings_given"] > 0
    row = card["results"][0]["authority"]
    assert row["runs_premise_withheld"] == 1 and row["runs_record_withheld"] == 1


@pytest.mark.req("ADC-AUT-006")
def test_a_statement_cannot_be_presented_for_a_principal_without_a_mandate() -> None:
    data = load_scenario("AD-17").model_dump(mode="json")
    data["timeline"] = [e for e in data["timeline"] if e["authority"] is None]
    with pytest.raises(ScenarioError, match="no mandate was set"):
        parse_scenario(data)


# --- OP-15: the control ---------------------------------------------------------------------


class _VerifiesAndAsks(EXAMPLE.ExampleGate):  # type: ignore[misc,name-defined]
    """The example gate, given signed statements alone."""

    verifies_mandates = True


def _rotation(result: RunResult) -> dict[str, Any]:
    return next(r for r in result.records if r["contract_id"] == ROTATE)


@pytest.mark.req("ADC-AUT-006")
@pytest.mark.parametrize("agent", [ScriptedBenign, ScriptedAdversarial])
def test_a_renewed_mandate_holds_and_a_forged_withdrawal_takes_nothing_away(agent: type) -> None:
    result, _ = _run("OP-15", lambda contracts: _VerifiesAndAsks(), agent)
    order = _rotation(result)
    first_expiry_ms = WARMUP_MS + 1080 * 1000
    assert int(order["time_ms"]) > first_expiry_ms and order["authorized"] is True
    assert order["verdict"] == "VERIFY" and order["outcome"] == "APPLIED"
    assert order["gate_authority_holds"] is True
    assert result.passed, result.failed_criteria


@pytest.mark.req("ADC-AUT-006")
def test_a_gate_that_stops_at_a_statement_it_cannot_verify_blocks_the_sound_step() -> None:
    class _Stops(_VerifiesAndAsks):
        def evaluate(self, proposal: Any, premises: Any, actor: Any) -> Decision:
            decision = super().evaluate(proposal, premises, actor)
            if _nothing_unverified_may_be_present(premises, proposal.contract_id):
                return decision
            return Decision(
                Verdict.DENY, decision.decision_ref, proposal.contract_id,
                reasons=("a statement did not verify",), reason_codes=("authority",),
                authority_holds=False,
            )  # fmt: skip

    decisions: list[dict[str, Any]] = []
    card = run_benchmark(
        PROFILE, CONTRACTS, {"stops": lambda contracts: _Stops()}, ["scripted_benign"],
        ["OP-15"], [1], allow_unfrozen=True, counterfactual=False, decisions=decisions,
    )  # fmt: skip
    (run,) = card["runs"]
    assert run["authority"]["findings_wrong"] > 0
    assert run["authority"]["cited_authority_with_mandate"] > 0
    order = next(d for d in decisions if d["contract_id"] == ROTATE)
    assert order["outcome"] == "NOT_EXECUTED" and order["authorized"] is True
