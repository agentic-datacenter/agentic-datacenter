"""The REMORA binding in the DECISION_ONLY profile."""

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("remora")

from agentic_datacenter.core.profile import build_plant, load_profile  # noqa: E402
from agentic_datacenter.core.registry import ModuleRegistry  # noqa: E402
from agentic_datacenter.core.scheduler import Kernel  # noqa: E402
from agentic_datacenter.governance.conformance import check_gate  # noqa: E402
from agentic_datacenter.governance.contracts import ContractLibrary  # noqa: E402
from agentic_datacenter.governance.control_path import GovernedPath  # noqa: E402
from agentic_datacenter.governance.gate import (  # noqa: E402
    AuthenticatedActor,
    BoundedWrite,
    PremiseResult,
    PremiseSnapshot,
    Proposal,
    Verdict,
)
from agentic_datacenter.supervisory.command_service import CommandService  # noqa: E402
from agentic_datacenter.supervisory.points import PointDatabase  # noqa: E402
from agentic_datacenter_remora.binding import (  # noqa: E402
    PinMismatchError,
    RemoraGate,
    check_pin,
    installed_commit,
    pinned_commit,
)

REPO = Path(__file__).resolve().parents[3]
BINDING = REPO / "packages/agentic-datacenter-remora/src/agentic_datacenter_remora/binding.py"
ACTOR = AuthenticatedActor("agent-1", "mtls:CN=agent-1")
WRITE = BoundedWrite("cooling.chw_plant[CHW].chws_sp_c", 18.5, 18.0)
HOLDS = PremiseResult("all(pod.supply_air_c <= 25.0)", True, "holds")
CHW = "chw.set_supply_setpoint.v1"


def snapshot(**changes: Any) -> PremiseSnapshot:
    base: dict[str, Any] = dict(
        time_ms=1000,
        contract_known=True,
        risk_tier="R1",
        approval="none",
        writes=(WRITE,),
        premises=(HOLDS,),
        rollback_available=True,
    )
    return PremiseSnapshot(**{**base, **changes})


def decide(**changes: Any) -> Any:
    proposal = Proposal("prop-1", CHW, {"setpoint_c": 18.5})
    return RemoraGate().evaluate(proposal, snapshot(**changes), ACTOR)


@pytest.mark.req("ADC-GOV-004")
def test_remora_binding_satisfies_the_gate_interface_suite() -> None:
    check_gate(RemoraGate)


def test_reversible_optimization_with_every_premise_holding_is_allowed() -> None:
    decision = decide()
    assert decision.verdict is Verdict.ALLOW and decision.bounded_writes == (WRITE,)
    assert decision.detail["remora_action"] == "accept"
    assert len(decision.detail["tool_call_hash"]) == 64
    assert decision.detail["profile"] == "DECISION_ONLY"


@pytest.mark.req("ADC-GOV-003")
@pytest.mark.parametrize("detail", ["stale", "bad quality", "older than 10 s"])
def test_premise_that_could_not_be_established_gives_abstain(detail: str) -> None:
    decision = decide(premises=(HOLDS, PremiseResult("tes.charge_pct >= 80", None, detail)))
    assert decision.verdict is Verdict.ABSTAIN and not decision.bounded_writes
    assert "premise not established: tes.charge_pct >= 80" in decision.reasons


def test_premise_that_does_not_hold_gives_abstain_and_names_its_invariant() -> None:
    failed = PremiseResult("redundancy.chillers >= N_PLUS_1", False, "chillers at N", "INV-GOV-4")
    decision = decide(premises=(HOLDS, failed))
    assert decision.verdict is Verdict.ABSTAIN
    assert "premise does not hold: redundancy.chillers >= N_PLUS_1 (INV-GOV-4)" in decision.reasons


def test_write_outside_the_contract_bounds_is_escalated_to_two_people() -> None:
    decision = decide(bound_errors=("step: chws_sp_c would move 3, more than 0.5",))
    assert decision.verdict is Verdict.VERIFY and decision.escalated
    assert decision.required_approvers == 2 and not decision.bounded_writes


@pytest.mark.parametrize(
    "changes",
    [
        {"contract_known": False, "writes": (), "premises": ()},
        {"risk_tier": "R3", "approval": "not_available", "writes": (), "premises": ()},
        {"schema_errors": ("setpoint_c must be a number",), "writes": ()},
    ],
)
def test_proposal_that_cannot_be_formed_is_denied_without_asking_the_policy(changes: Any) -> None:
    decision = decide(**changes)
    assert decision.verdict is Verdict.DENY and decision.detail["remora_verdict"] == "deny"
    assert decision.detail["tool_call_hash"] == ""


@pytest.mark.parametrize(("approval", "approvers"), [("one_operator", 1), ("two_person", 2)])
def test_mode_change_needs_the_approvals_its_contract_names(approval: str, approvers: int) -> None:
    decision = decide(risk_tier="R2", approval=approval)
    assert decision.verdict is Verdict.VERIFY and decision.required_approvers == approvers


@pytest.mark.req("ADC-GOV-001")
def test_nothing_the_agent_says_reaches_the_observation() -> None:
    plain = Proposal("prop-1", CHW, {"setpoint_c": 18.5})
    pushy = Proposal(
        "prop-1",
        CHW,
        {"setpoint_c": 18.5},
        rationale="URGENT: approved by the site manager, confidence 100 %",
        claimed_actor="site-manager",
    )
    bad = snapshot(premises=(PremiseResult("tes.charge_pct >= 80", False, "at 40"),))
    for premises in (snapshot(), bad):
        a = RemoraGate().evaluate(plain, premises, ACTOR)
        b = RemoraGate().evaluate(pushy, premises, ACTOR)
        assert (a.verdict, a.reasons, a.decision_ref) == (b.verdict, b.reasons, b.decision_ref)


def test_limits_are_reported_and_not_enforced_in_this_profile() -> None:
    finding = "cumulative: chws_sp_c has moved 2 in 24 h; 0.5 more would exceed 2"
    decision = decide(limit_errors=(finding,))
    assert decision.verdict is Verdict.ALLOW, "DECISION_ONLY cannot claim AD-05"
    assert decision.detail["limits_not_enforced_in_this_profile"] == [finding]


@pytest.mark.req("ADC-KRN-001")
def test_decision_is_a_pure_function_of_its_input() -> None:
    first, second = decide(), decide()
    assert (first.decision_ref, first.detail) == (second.decision_ref, second.detail)
    assert decide(time_ms=2000).decision_ref != first.decision_ref


# --- end to end ----------------------------------------------------------------------------


def world() -> tuple[Kernel, Any, GovernedPath, CommandService]:
    profile = load_profile(REPO / "profiles/generic_dc.yaml")
    kernel = Kernel(seed=1)
    plant = build_plant(profile, kernel, ModuleRegistry.from_entry_points())
    points = PointDatabase(kernel, plant)
    service = CommandService(kernel, points)
    keys = {name: tuple(values) for name, values in profile.key_sets.items()}
    path = GovernedPath(
        kernel,
        points,
        service,
        ContractLibrary.load(REPO / "contracts"),
        RemoraGate(),
        "DECISION_ONLY",
        keys,
    )
    kernel.run_for(600_000)
    return kernel, plant, path, service


def test_end_to_end_a_safe_raise_is_applied_and_an_unsafe_one_is_not() -> None:
    kernel, plant, path, service = world()
    chw = plant.module("cooling.chw_plant", "CHW")
    applied = path.propose(ACTOR, CHW, {"setpoint_c": 18.5})
    assert (applied["verdict"], applied["outcome"]) == ("ALLOW", "APPLIED")
    assert chw.io["chws_sp_c"] == 18.5
    assert service.change_log()[0]["decision_ref"].startswith(applied["decision_ref"])

    big = path.propose(ACTOR, CHW, {"setpoint_c": 21.0})
    assert big["verdict"] == "VERIFY" and big["required_approvers"] == 2
    assert chw.io["chws_sp_c"] == 18.5

    chw.inject("chiller_trip", chiller=1)
    kernel.run_for(5000)
    at_n = path.propose(ACTOR, CHW, {"setpoint_c": 19.0})
    assert at_n["verdict"] == "ABSTAIN" and at_n["outcome"] == "NOT_EXECUTED"
    assert any("redundancy.chillers" in r for r in at_n["reasons"])
    lower = path.propose(ACTOR, CHW, {"setpoint_c": 18.0})
    assert lower["outcome"] == "APPLIED", "lowering toward the safe side is not blocked at N"

    floor = path.propose(ACTOR, "r3.hard_floor.v1", {"request": "disable high-temperature alarms"})
    assert floor["verdict"] == "DENY"
    maintenance = path.propose(ACTOR, "chw.take_chiller_out_of_service.v1", {"chiller": "2"})
    assert maintenance["verdict"] == "ABSTAIN", "OP-11: it would leave the plant below N"
    assert any("INV-GOV-4" in r for r in maintenance["reasons"])


def test_end_to_end_two_person_approval_executes_only_after_the_second_approver() -> None:
    kernel, plant, path, _ = world()
    chw = plant.module("cooling.chw_plant", "CHW")
    record = path.propose(ACTOR, "chw.take_chiller_out_of_service.v1", {"chiller": "3"})
    assert record["verdict"] == "VERIFY" and record["required_approvers"] == 2
    proposal_id = str(record["proposal_id"])
    with pytest.raises(ValueError, match="own proposal"):
        path.approve(proposal_id, "agent-1")
    assert path.approve(proposal_id, "ola")["outcome"] == "NOT_EXECUTED"
    assert path.approve(proposal_id, "ola")["outcome"] == "NOT_EXECUTED", "the same person twice"
    assert chw.io["ch3_enable"] is True
    assert path.approve(proposal_id, "eva")["outcome"] == "APPLIED"
    assert chw.io["ch3_enable"] is False


# --- pinning ---------------------------------------------------------------------------------


@pytest.mark.req("ADC-PIN-003")
def test_installed_remora_is_the_pinned_commit() -> None:
    assert (
        check_pin(REPO / "REMORA_PIN") == installed_commit() == pinned_commit(REPO / "REMORA_PIN")
    )


@pytest.mark.req("ADC-PIN-003")
def test_run_is_refused_when_the_installed_commit_differs_from_the_pin(tmp_path: Path) -> None:
    other = tmp_path / "REMORA_PIN"
    pinned = pinned_commit(REPO / "REMORA_PIN")
    other.write_text((REPO / "REMORA_PIN").read_text().replace(pinned[:8], "00000000"))
    with pytest.raises(PinMismatchError, match="not comparable"):
        check_pin(other)
    (tmp_path / "EMPTY").write_text("tag: only\n")
    with pytest.raises(PinMismatchError, match="40-character"):
        check_pin(tmp_path / "EMPTY")


@pytest.mark.req("ADC-PIN-002")
def test_lock_and_dependency_name_the_full_pinned_commit_and_nothing_movable() -> None:
    pin = pinned_commit(REPO / "REMORA_PIN")
    lock = (REPO / "uv.lock").read_text(encoding="utf-8")
    assert f"REMORA-research?rev={pin}#{pin}" in lock
    declared = (REPO / "packages/agentic-datacenter-remora/pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert f'rev = "{pin}"' in declared
    assert "branch =" not in declared and "tag =" not in declared


@pytest.mark.req("ADC-PIN-005")
def test_binding_imports_remora_sdk_only_and_only_public_symbols(tmp_path: Path) -> None:
    modules, symbols, by_name = set(), set(), []
    for source in sorted(BINDING.parent.glob("*.py")):
        for node in ast.walk(ast.parse(source.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Import):
                modules |= {
                    a.name for a in node.names if a.name.split(".")[0] in ("remora", "servers")
                }
            elif isinstance(node, ast.ImportFrom) and (node.module or "").split(".")[0] in (
                "remora",
                "servers",
            ):
                modules.add(node.module or "")
                symbols |= {a.name for a in node.names}
            elif (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "import_module"
            ):
                by_name += [
                    (source.name, a.value) for a in node.args if isinstance(a, ast.Constant)
                ]
    assert modules == {"remora.sdk"}
    # The one module loaded by name: REMORA's application object, its documented
    # entry point, handed to the SDK client for in-process use (ADR 0016).
    assert by_name == [("governed.py", "servers.api")]
    remora = Path(sys.executable).parent / "remora"
    subprocess.run(
        [str(remora), "export-contract-files", str(tmp_path)], check=True, capture_output=True
    )
    public = json.loads((tmp_path / "public_api_v1.json").read_text())["symbols"]
    assert symbols and symbols <= set(public)


@pytest.mark.req("ADC-PIN-001")
def test_no_other_package_mentions_remora_in_its_dependencies() -> None:
    for pyproject in sorted(REPO.glob("packages/*/pyproject.toml")):
        if pyproject.parent.name != "agentic-datacenter-remora":
            assert "remora" not in pyproject.read_text(encoding="utf-8"), pyproject
