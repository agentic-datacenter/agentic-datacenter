"""REMORA's governed execution path as a gate: the GOVERNED and SHADOW profiles."""

from __future__ import annotations

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
from agentic_datacenter.governance.gate import AuthenticatedActor, Outcome  # noqa: E402
from agentic_datacenter.supervisory.command_service import CommandService  # noqa: E402
from agentic_datacenter.supervisory.points import PointDatabase  # noqa: E402
from agentic_datacenter_remora.binding import PinMismatchError  # noqa: E402
from agentic_datacenter_remora.governed import GovernedRemoraGate, ShadowRemoraGate  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
LIBRARY = ContractLibrary.load(REPO / "contracts")
ACTOR = AuthenticatedActor("agent-1", "mtls:CN=agent-1")
CHW = "chw.set_supply_setpoint.v1"
CHWS = "cooling.chw_plant[CHW].chws_sp_c"
HALF_HOUR_MS = 31 * 60 * 1000


class World:
    def __init__(self, gate: Any = None, writes_per_minute: int = 10) -> None:
        profile = load_profile(REPO / "profiles/generic_dc.yaml")
        self.kernel = Kernel(seed=1)
        self.plant = build_plant(profile, self.kernel, ModuleRegistry.from_entry_points())
        self.points = PointDatabase(self.kernel, self.plant)
        self.service = CommandService(self.kernel, self.points, writes_per_minute)
        self.gate = gate or GovernedRemoraGate(LIBRARY, verify_pin=False)
        keys = {name: tuple(values) for name, values in profile.key_sets.items()}
        self.path = GovernedPath(
            self.kernel, self.points, self.service, LIBRARY, self.gate, self.gate.profile, keys
        )
        self.kernel.run_for(600_000)

    def setpoint(self) -> float:
        return float(self.plant.module("cooling.chw_plant", "CHW").io["chws_sp_c"])

    def move(self, to: float, approve: bool = True) -> dict[str, Any]:
        record = self.path.propose(ACTOR, CHW, {"setpoint_c": to})
        if approve and record["verdict"] == "VERIFY":
            record = self.path.approve(str(record["proposal_id"]), "operator-ola")
        return record


@pytest.mark.req("ADC-GOV-004")
def test_governed_binding_satisfies_the_gate_interface_suite() -> None:
    check_gate(lambda: GovernedRemoraGate(LIBRARY, verify_pin=False))


@pytest.mark.req("ADC-GOV-002")
def test_a_bounded_reversible_step_runs_without_a_person() -> None:
    world = World()
    done = world.move(18.5, approve=False)
    assert (done["verdict"], done["outcome"]) == ("ALLOW", "APPLIED")
    assert done["required_approvers"] == 0 and done["approvers"] == []
    assert "remora:bounded_write_accept" in done["reasons"]
    assert world.setpoint() == 18.5
    assert "EFFECT_VERIFIED (computed)" in done["outcome_detail"]
    entry = world.service.change_log()[0]
    assert entry["accepted"] and str(entry["decision_ref"]).startswith(str(done["decision_ref"]))


@pytest.mark.req("ADC-GOV-002")
def test_a_step_without_a_rollback_is_released_only_after_a_person_approves() -> None:
    world = World()
    waiting = world.path.propose(
        ACTOR, "chw.precool.v1", {"setpoint_c": 17.5, "forecast_peak_c": 35.0}
    )
    assert (waiting["verdict"], waiting["outcome"]) == ("VERIFY", "NOT_EXECUTED")
    assert waiting["required_approvers"] == 1 and world.setpoint() == 18.0
    assert world.service.change_log() == []
    done = world.path.approve(str(waiting["proposal_id"]), "operator-ola")
    assert done["outcome"] == "APPLIED" and world.setpoint() == 17.5


def test_a_contract_that_names_an_operator_still_needs_one() -> None:
    world = World()
    record = world.path.propose(ACTOR, "genset.start_test_run.v1", {"train": "A"})
    assert record["verdict"] == "VERIFY" and record["required_approvers"] == 1
    assert world.service.change_log() == []


@pytest.mark.req("ADC-GOV-002")
def test_a_spent_authorization_cannot_be_used_again() -> None:
    world = World()
    done = world.move(18.5)
    assert done["outcome"] == "APPLIED"
    called = []

    def apply() -> tuple[str, str]:
        called.append(1)
        return "APPLIED", ""

    again = world.gate.execute(
        str(done["decision_ref"]), world.kernel.clock.now_ms, apply, lambda tag: 18.5
    )
    assert again.status == "REJECTED" and again.detail.startswith("remora:")
    assert called == [] and len(world.service.change_log()) == 2
    unknown = world.gate.execute("dec-never-issued", 0, apply, lambda tag: 0.0)
    assert unknown == Outcome("REJECTED", "REMORA holds no authorization under this reference")


def test_two_people_means_two_credentials() -> None:
    world = World()
    chw = world.plant.module("cooling.chw_plant", "CHW")
    record = world.path.propose(ACTOR, "chw.take_chiller_out_of_service.v1", {"chiller": "3"})
    assert record["verdict"] == "VERIFY" and record["required_approvers"] == 2
    proposal = str(record["proposal_id"])
    assert world.path.approve(proposal, "operator-ola")["outcome"] == "NOT_EXECUTED"
    assert world.path.approve(proposal, "operator-ola")["approvers"] == ["operator-ola"]
    assert chw.io["ch3_enable"] is True
    assert world.path.approve(proposal, "operator-eva")["outcome"] == "APPLIED"
    assert chw.io["ch3_enable"] is False
    listed = next(p for p in world.gate.evidence()["proposals"] if p["outcome"] == "APPLIED")
    assert len(set(listed["approved_by"])) == 2


@pytest.mark.req("ADC-GOV-001")
def test_the_cumulative_limit_is_held_on_remoras_ledger() -> None:
    world = World()
    for target in (17.5, 17.0, 17.5, 18.0):  # four moves of 0.5: the 2.0 the contract allows
        assert world.move(target)["outcome"] == "APPLIED", target
        world.kernel.run_for(HALF_HOUR_MS)
    refused = world.move(17.5)
    assert refused["verdict"] == "DENY" and refused["outcome"] == "NOT_EXECUTED"
    assert any("limit_exceeded" in reason for reason in refused["reasons"])
    assert world.setpoint() == 18.0


@pytest.mark.req("ADC-GOV-001")
def test_a_step_back_is_assessed_under_the_restore_tool_and_not_held_by_the_rate() -> None:
    """INV-GOV-8, scenario AD-03: the two raises spend the hour's rate; the way back is open."""
    world = World()
    assert world.move(18.5)["outcome"] == "APPLIED"
    assert world.move(19.0)["outcome"] == "APPLIED"
    up = world.move(19.5)
    assert up["verdict"] == "DENY" and any("limit_exceeded" in r for r in up["reasons"])
    back = world.move(18.5, approve=False)
    assert (back["verdict"], back["outcome"]) == ("ALLOW", "APPLIED")
    assert "remora:bounded_write_accept" in back["reasons"]
    assert world.setpoint() == 18.5
    past = world.move(17.5, approve=False)
    assert past["verdict"] != "ALLOW", "past where the agent started is not a step back"


@pytest.mark.req("ADC-GOV-001")
def test_the_rate_of_a_contract_is_held_on_remoras_ledger() -> None:
    world = World()
    assert world.move(17.9)["outcome"] == "APPLIED"
    assert world.move(17.8)["outcome"] == "APPLIED"
    third = world.move(17.7)
    assert third["verdict"] == "DENY" and any("limit_exceeded" in r for r in third["reasons"])
    assert world.setpoint() == 17.8


def test_an_approval_that_comes_too_late_is_not_taken() -> None:
    world = World()
    waiting = world.path.propose(ACTOR, "genset.start_test_run.v1", {"train": "A"})
    assert waiting["verdict"] == "VERIFY"
    world.kernel.run_for(5 * 3600 * 1000)
    late = world.path.approve(str(waiting["proposal_id"]), "operator-ola")
    assert late["outcome"] != "APPLIED" and world.service.change_log() == []
    assert late["approval_refusals"] and "operator-ola: remora:" in late["approval_refusals"][0]


@pytest.mark.req("ADC-GOV-007")
@pytest.mark.parametrize(("landed", "final"), [(True, "APPLIED"), (False, "REJECTED")])
def test_an_unanswered_write_is_unknown_until_the_plant_is_read(landed: bool, final: str) -> None:
    world = World()
    pumps = world.plant.module("cooling.pump_station", "PHPS")
    before = float(pumps.io["dp_sp_kpa"])
    world.service.fail_next(applied=landed)
    record = world.path.propose(ACTOR, "pumps.set_dp_setpoint.v1", {"dp_kpa": before + 5.0})
    assert record["outcome"] == "UNKNOWN" and record["was_unknown"] is True
    assert pumps.io["dp_sp_kpa"] == (before + 5.0 if landed else before)
    reviewer = world.gate._service.clients["reviewer"]
    assert len(reviewer.list_unresolved()) == 1, "REMORA holds the outcome as unknown"
    assert [e["code"] for e in world.service.change_log()] == ["TIMEOUT"]

    world.kernel.run_for(31_000)
    resolved = world.path.record(str(record["proposal_id"]))
    assert resolved["outcome"] == final and "independent read" in resolved["outcome_detail"]
    assert "gate: resolved" in resolved["outcome_detail"]
    assert len(reviewer.list_unresolved()) == 0
    assert [e["code"] for e in world.service.change_log()] == ["TIMEOUT"], "never sent again"
    again = world.gate.execute(
        str(record["decision_ref"]), world.kernel.clock.now_ms,
        lambda: ("APPLIED", ""), lambda tag: before,
    )  # fmt: skip
    assert again.status == "REJECTED", "the grant is spent; a further attempt needs a proposal"


@pytest.mark.req("ADC-GOV-007")
def test_half_a_contract_instance_is_restored_when_the_plant_is_read() -> None:
    world = World()
    world.service.fail_next(applied=True)  # the first of two writes lands, unanswered
    record = world.move(18.5)
    assert record["outcome"] == "UNKNOWN" and world.setpoint() == 18.5
    world.kernel.run_for(31_000)
    resolved = world.path.record(str(record["proposal_id"]))
    assert resolved["outcome"] == "ROLLED_BACK" and "1 of 2 writes" in resolved["outcome_detail"]
    assert world.setpoint() == 18.0
    assert len(world.gate._service.clients["reviewer"].list_unresolved()) == 0


def test_a_write_the_command_service_refuses_gives_its_budget_back() -> None:
    world = World(writes_per_minute=0)
    record = world.move(18.5)
    assert record["outcome"] == "REJECTED" and "RATE_LIMITED" in record["outcome_detail"]
    assert world.setpoint() == 18.0
    assert len(world.gate._service.clients["reviewer"].list_unresolved()) == 0


def test_shadow_records_the_decision_and_executes_nothing() -> None:
    world = World(ShadowRemoraGate(LIBRARY, verify_pin=False))
    record = world.move(18.5)
    assert record["verdict"] == "ALLOW" and record["outcome"] == "NOT_EXECUTED"
    assert "shadow" in record["outcome_detail"]
    assert world.setpoint() == 18.0 and world.service.change_log() == []


def test_the_run_is_tied_to_remoras_own_records() -> None:
    world = World()
    world.move(18.5)
    evidence = world.gate.evidence()
    assert evidence["profile"] == "GOVERNED"
    assert (
        evidence["audit_chain"]["valid"] is True and evidence["audit_chain"]["records_checked"] > 0
    )
    assert evidence["artifacts"]["label"] == "simulator artifact, not for production"
    assert [p["outcome"] for p in evidence["proposals"]] == ["APPLIED"]


def test_two_runs_give_the_same_decision_references() -> None:
    first, second = World(), World()
    a, b = first.move(18.5), second.move(18.5)
    assert a["decision_ref"] == b["decision_ref"] and a["reasons"] == b["reasons"]
    assert first.kernel.state_hash() == second.kernel.state_hash()


@pytest.mark.req("ADC-PIN-003")
def test_a_governed_run_is_refused_when_remora_is_not_the_pinned_commit(tmp_path: Path) -> None:
    pin = tmp_path / "REMORA_PIN"
    pin.write_text("commit:      " + "0" * 40 + "\n", encoding="utf-8")
    with pytest.raises(PinMismatchError):
        GovernedRemoraGate(LIBRARY, pin_file=pin)
    with pytest.raises(PinMismatchError, match="no REMORA_PIN"):
        ShadowRemoraGate(LIBRARY, pin_file=tmp_path / "missing")


@pytest.mark.req("ADC-BEN-003")
@pytest.mark.req("ADC-BEN-008")
def test_branches_from_a_snapshot_of_remora_judge_as_branches_from_the_start() -> None:
    """REMORA's ledgers cannot be captured with the plant; a snapshot of them stands in."""
    from agentic_datacenter.scenarios.agents import ScriptedAdversarial
    from agentic_datacenter.scenarios.counterfactual import judge_run
    from agentic_datacenter.scenarios.scenario import load_scenario

    def create(contracts: ContractLibrary) -> GovernedRemoraGate:
        return GovernedRemoraGate(contracts, verify_pin=False)

    def judged(snapshots: bool) -> tuple[dict[str, Any], list[Any]]:
        result, judgements = judge_run(
            load_scenario("AD-03"), load_profile(REPO / "profiles/generic_dc.yaml"), create,
            "GOVERNED", ScriptedAdversarial, 1, LIBRARY, 1200, horizon_s=600,
            gate_snapshots=snapshots,
        )  # fmt: skip
        return dict(result.judging), judgements

    (fast, from_snapshot), (slow, from_start) = judged(True), judged(False)
    assert fast["branches_from"] == "gate snapshot" and slow["branches_from"] == "start of run"
    assert from_snapshot and from_snapshot == from_start
