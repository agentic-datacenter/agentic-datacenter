"""Safe posture: an applied step never outlives its premises, and a step back is never held.

Scenario AD-03 showed both gaps. Two raises of the chilled water setpoint were
allowed on premises that held at the time; then three zone sensor arrays went
4 K low. The step stayed in place, and the agent's step back down was refused
for an hour by the contract's rate limit.
"""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.governance.agent_tools.server import AgentTools
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary, parse_contract
from agentic_datacenter.governance.control_path import PREMISE_LOSS_HOLD_S, GovernedPath
from agentic_datacenter.governance.gate import AuthenticatedActor, GovernanceGate
from agentic_datacenter.governance.premises import AppliedWrite, PremiseReader, build_snapshot
from agentic_datacenter.supervisory.command_service import CommandService
from agentic_datacenter.supervisory.overview import Overview
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[3]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
KEYS = {name: tuple(keys) for name, keys in PROFILE.key_sets.items()}
AGENT = AuthenticatedActor("agent-1", "mtls:CN=agent-1")
CHW = "chw.set_supply_setpoint.v1"
CHWS = "cooling.chw_plant[CHW].chws_sp_c"
TES = "cooling.tes[TES-1].supply_sp_c"


class World:
    def __init__(
        self, gate: GovernanceGate, profile: str, library: ContractLibrary | None = None
    ) -> None:
        self.kernel = Kernel(seed=1)
        self.plant = build_plant(PROFILE, self.kernel, ModuleRegistry.from_entry_points())
        self.points = PointDatabase(self.kernel, self.plant)
        self.service = CommandService(self.kernel, self.points)
        self.library = library or ContractLibrary.load(REPO / "contracts")
        self.path = GovernedPath(
            self.kernel, self.points, self.service, self.library, gate, profile, KEYS
        )
        self.tools = AgentTools(AGENT, self.points, self.path)
        self.kernel.run_for(600_000)

    def chws(self) -> Any:
        return self.plant.module("cooling.chw_plant", "CHW").io["chws_sp_c"]

    def bias_pod(self, pod: str, offset: float) -> None:
        for n in range(1, 7):
            self.plant.module("sensors", "SENSORS").inject(
                "bias", tag=f"cooling.pod[{pod}].zone_t{n}", offset=offset
            )

    def raise_twice(self) -> list[dict[str, Any]]:
        first = self.tools.propose_action(CHW, {"setpoint_c": 18.5})
        self.kernel.run_for(300_000)
        second = self.tools.propose_action(CHW, {"setpoint_c": 19.0})
        assert first["outcome"] == second["outcome"] == "APPLIED"
        return [first, second]


@pytest.mark.req("ADC-GOV-001")
def test_an_applied_raise_is_undone_when_a_premise_it_was_allowed_on_stops_holding() -> None:
    """INV-GOV-7, scenario AD-03: biased sensors raise an inconsistency alarm after the step."""
    world = World(NullGate(), "DECISION_ONLY")
    _, second = world.raise_twice()
    world.bias_pod("03", -4.0)
    world.kernel.run_for(30_000 + PREMISE_LOSS_HOLD_S * 1000)
    after = world.path.record(str(second["proposal_id"]))
    assert after["outcome"] == "ROLLED_BACK"
    assert world.path.record(str(_["proposal_id"]))["outcome"] == "ROLLED_BACK", "both raises"
    assert "premise no longer holds: no_active_alarm" in str(after["outcome_detail"])
    assert world.chws() == 18.0, "back to before the first raise, not only the last"
    last = world.service.change_log()[-2:]
    assert [(e["tag"], e["new"], e["actor"]) for e in last] == [
        (CHWS, 18.0, "rollback-monitor"),
        (TES, 18.0, "rollback-monitor"),
    ]
    assert world.path.restore_origins() == {}


def test_a_premise_that_can_no_longer_be_established_undoes_the_step_too() -> None:
    """INV-GOV-3 carried past the decision: not knowing is not a reason to stay."""
    world = World(NullGate(), "DECISION_ONLY")
    record = world.tools.propose_action(CHW, {"setpoint_c": 18.5})
    world.points.set_link(False)
    world.kernel.run_for(40_000)
    held = world.path.record(str(record["proposal_id"]))
    assert held["outcome"] == "APPLIED", "nothing can be written while the link is down"
    assert world.service.change_log()[-1]["code"] == "LINK_DOWN"
    world.points.set_link(True)
    world.kernel.run_for(5_000)
    after = world.path.record(str(record["proposal_id"]))
    assert after["outcome"] == "ROLLED_BACK" and world.chws() == 18.0
    assert "not established" in str(after["outcome_detail"]), "decided while it could not be read"


def test_a_short_lapse_of_a_premise_does_not_undo_the_step() -> None:
    world = World(NullGate(), "DECISION_ONLY")
    record = world.tools.propose_action(CHW, {"setpoint_c": 18.5})
    world.bias_pod("03", -4.0)
    world.kernel.run_for((PREMISE_LOSS_HOLD_S - 4) * 1000)
    world.bias_pod("03", 0.0)
    world.kernel.run_for(60_000)
    assert world.path.record(str(record["proposal_id"]))["outcome"] == "APPLIED"
    assert world.chws() == 18.5


def test_a_rollback_trigger_that_cannot_be_read_counts_as_fired() -> None:
    contract = parse_contract({
        "schema_version": 1, "id": "chw.trial.v1", "title": "trial", "risk_tier": "R1",
        "arguments": {"setpoint_c": {"type": "number"}},
        "writes": [{"tag": CHWS, "value": "setpoint_c",
                    "bounds": {"min": 16.0, "max": 21.0, "max_step": 0.5}}],
        "rollback": {"trigger": "any(pod.supply_air_c > 26.0) for 5s",
                     "action": "restore_previous"},
        "approval": "none",
    })  # fmt: skip
    world = World(NullGate(), "DECISION_ONLY", ContractLibrary([contract]))
    record = world.tools.propose_action("chw.trial.v1", {"setpoint_c": 18.5})
    assert record["outcome"] == "APPLIED"
    world.points.set_link(False)
    world.kernel.run_for(30_000)
    world.points.set_link(True)
    world.kernel.run_for(3_000)
    after = world.path.record(str(record["proposal_id"]))
    assert after["outcome"] == "ROLLED_BACK" and world.chws() == 18.0
    assert after["outcome_detail"] == "any(pod.supply_air_c > 26.0) for 5s"


def test_nothing_is_watched_without_a_gate() -> None:
    world = World(NullGate(), "UNGOVERNED")
    world.raise_twice()
    world.bias_pod("03", -4.0)
    world.kernel.run_for(60_000)
    assert world.chws() == 19.0


# --- the step back -----------------------------------------------------------------------


def _snapshot(world: World, value: float, origins: dict[str, float]) -> Any:
    now = world.kernel.clock.now_ms
    history = [
        AppliedWrite(now - 600_000, CHW, CHWS, 0.5),
        AppliedWrite(now - 300_000, CHW, CHWS, 0.5),
    ]
    return build_snapshot(
        world.library.get(CHW), {"setpoint_c": value},
        PremiseReader(world.points, Overview(world.points)), world.points, KEYS, history, now,
        origins,
    )  # fmt: skip


@pytest.mark.req("ADC-GOV-001")
def test_a_step_back_toward_where_the_agent_started_is_not_held_by_a_limit() -> None:
    """INV-GOV-8: the rate limit was spent on two raises; the way back stays open."""
    world = World(NullGate(), "UNGOVERNED")
    world.raise_twice()
    world.kernel.run_for(2_000)
    origin = {CHWS: 18.0, TES: 18.0}
    back = _snapshot(world, 18.5, origin)
    assert back.restore and back.limit_errors == () and back.bound_errors == ()
    up = _snapshot(world, 19.5, origin)
    assert not up.restore and any(e.startswith("rate:") for e in up.limit_errors)


@pytest.mark.parametrize(
    ("value", "origins", "why"),
    [
        (17.5, {CHWS: 18.0, TES: 18.0}, "past the value the agent started from"),
        (18.5, {}, "no standing write of the agent's to go back from"),
        (18.5, {CHWS: 18.0}, "one of the two points has no standing write"),
    ],
)
def test_only_a_step_back_to_where_the_agent_started_is_a_restore(
    value: float, origins: dict[str, float], why: str
) -> None:
    world = World(NullGate(), "UNGOVERNED")
    world.raise_twice()
    world.kernel.run_for(2_000)
    snapshot = _snapshot(world, value, origins)
    assert not snapshot.restore, why
    assert any(e.startswith("rate:") for e in snapshot.limit_errors)


def test_the_path_offers_the_origins_of_the_points_it_watches() -> None:
    world = World(NullGate(), "DECISION_ONLY")
    world.raise_twice()
    assert world.path.restore_origins() == {CHWS: 18.0, TES: 18.0}
    back = world.tools.propose_action(CHW, {"setpoint_c": 18.0})
    assert back["outcome"] == "APPLIED"
    assert world.path.restore_origins() == {}, "back at the start: nothing left to watch"


def test_a_step_back_is_never_undone_for_a_lost_premise() -> None:
    world = World(NullGate(), "DECISION_ONLY")
    world.raise_twice()
    back = world.tools.propose_action(CHW, {"setpoint_c": 18.5})
    assert back["outcome"] == "APPLIED"
    world.bias_pod("03", -4.0)
    world.kernel.run_for(30_000 + PREMISE_LOSS_HOLD_S * 1000)
    assert world.chws() == 18.0, "the remaining undo goes further back, never up again"


def test_the_steps_that_are_undone_are_recorded_as_rolled_back_and_a_step_back_is_not() -> None:
    """Scenario OP-03: the agent steps back once, then the rest of the raise is undone."""
    world = World(NullGate(), "DECISION_ONLY")
    first, second = world.raise_twice()
    back = world.tools.propose_action(CHW, {"setpoint_c": 18.5})
    world.bias_pod("03", -4.0)
    world.kernel.run_for(30_000 + PREMISE_LOSS_HOLD_S * 1000)
    outcome = {r["proposal_id"]: r["outcome"] for r in world.path.records()}
    assert outcome[first["proposal_id"]] == outcome[second["proposal_id"]] == "ROLLED_BACK"
    assert outcome[back["proposal_id"]] == "APPLIED", "the step back was not undone"
    assert world.chws() == 18.0


def test_premise_watches_survive_a_snapshot_and_restore() -> None:
    world = World(NullGate(), "DECISION_ONLY")
    world.raise_twice()
    saved = world.kernel.snapshot()
    world.kernel.restore(saved)
    world.bias_pod("03", -4.0)
    world.kernel.run_for(30_000 + PREMISE_LOSS_HOLD_S * 1000)
    assert world.chws() == 18.0
