"""Play one what-if: three branches from one start state (ADR 0019, decision 2).

- A **baseline**: the plant as it is, under ``BASELINE_RULES``.
- B **physical**: the same, with every point the contract writes held at the
  target by a simulator-internal override from scenario time zero. Nothing is
  proposed, decided or written through the command service; the branch is
  hypothetical and labelled so everywhere.
- C **governed**: under ``GOVERNED``, a goal-seeking agent proposes contract
  steps toward the target through the agent tool surface.

Every branch is built the same way from the same scenario, profile, contracts
and seed, and its state hash after the warm-up must equal the others'. The
contract preflight and the policy analysis are computed on a separate start
run of the same request, and kept apart from the physics.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.gate import GovernanceGate
from agentic_datacenter.scenarios.bench import STATEMENTS, load_gates, lowest_fidelity
from agentic_datacenter.scenarios.harness import RunResult, ScenarioRun, World
from agentic_datacenter.whatif import policy as policy_analysis
from agentic_datacenter.whatif.agent import GoalSeekingAgent, stopped_because
from agentic_datacenter.whatif.compare import compare
from agentic_datacenter.whatif.metrics import Meter, governance_violations, physical_violations
from agentic_datacenter.whatif.models import WhatIfSpec, load_whatif_scenario
from agentic_datacenter.whatif.preflight import EPS, Study, check, key_sets, start_run, study

GateFactory = Callable[[ContractLibrary], GovernanceGate]
GOVERNED_GATE = "remora_governed"
LABELS = {
    "baseline": "A baseline: the plant as it is, with no change by any agent",
    "physical": (
        "B physical (hypothetical): the target held by a simulator-internal override; "
        "not proposed, not decided, not governed and not an agent action"
    ),
    "governed": (
        "C governed: a goal-seeking agent proposes contract steps toward the target, "
        "decided and executed under GOVERNED"
    ),
}
WHATIF_STATEMENTS = [
    "Branch B is hypothetical. Its points were held at the target by a simulator-internal "
    "override, never through the command service; it shows the physics of the change only, "
    "and it is never counted as a governance failure.",
    "Energy figures come from models at fidelity F1 and are model estimates. Differences "
    "between branches run on the same model mean more than their absolute values.",
    "The contract preflight and REMORA's policy analysis are advisory and reported apart "
    "from the physics. Neither grants, proposes or writes anything.",
]
NOT_APPLICABLE = (
    "not applicable: a hypothetical branch made by a simulator-internal override, with no "
    "proposal, decision or governed write"
)


@dataclass
class Hold:
    """The simulator-internal override of branch B: points held at one value.

    It writes the module's own I/O board, as a scenario input would, and wakes
    the module. It never touches the command service, carries no decision
    reference and is not reachable from the agent's tools.
    """

    tags: tuple[str, ...]
    value: float
    reasserted: int = 0

    def apply(self, world: World) -> int:
        """Put every held point at the value; return how many had moved."""
        moved = 0
        for tag in self.tags:
            module_part, _, point = tag.rpartition(".")
            module_id, _, rest = module_part.partition("[")
            module = world.plant.module(module_id, rest.rstrip("]"))
            board = module.io  # type: ignore[attr-defined]
            if board[point] != self.value:
                board[point] = self.value
                module.ctx.wake()
                moved += 1
        return moved

    def read(self, world: World) -> dict[str, float]:
        """Return the true value of every held point."""
        out = {}
        for tag in self.tags:
            module_part, _, point = tag.rpartition(".")
            module_id, _, rest = module_part.partition("[")
            board = world.plant.module(module_id, rest.rstrip("]")).io  # type: ignore[attr-defined]
            out[tag] = float(board[point])
        return out


@dataclass
class BranchResult:
    """One branch of a what-if."""

    name: str
    label: str
    hypothetical: bool
    available: bool = True
    unavailable_reason: str | None = None
    operating_profile: str = ""
    gate: str = ""
    agent: str = "none"
    start_state_hash: str = ""
    run: RunResult | None = None
    energy: dict[str, JsonValue] = field(default_factory=dict)
    physical: dict[str, float] = field(default_factory=dict)
    governance: dict[str, int] | None = None
    series: list[dict[str, JsonValue]] = field(default_factory=list)
    override: dict[str, Any] | None = None
    final_values: dict[str, float] = field(default_factory=dict)
    agent_log: list[dict[str, JsonValue]] = field(default_factory=list)
    outcome: dict[str, Any] | None = None

    def summary(self) -> dict[str, Any]:
        """Return the branch as JSON, without its series and run records."""
        out: dict[str, Any] = {
            "label": self.label, "hypothetical": self.hypothetical, "available": self.available,
        }  # fmt: skip
        if not self.available:
            out["unavailable_reason"] = self.unavailable_reason
            return out
        if self.hypothetical:
            governance: dict[str, Any] = {"applicable": False, "reason": NOT_APPLICABLE}
        else:
            governance = {"applicable": True, "violations": dict(self.governance or {})}
        out.update({
            "operating_profile": self.operating_profile, "gate": self.gate, "agent": self.agent,
            "start_state_hash": self.start_state_hash,
            "final_state_hash": self.run.state_hashes[-1][1] if self.run and self.run.state_hashes
            else "",
            "energy": self.energy, "physical": self.physical, "governance": governance,
            "final_values": self.final_values, "override": self.override,
            "outcome": self.outcome,
        })  # fmt: skip
        if self.run is not None:
            m = self.run.metrics
            out["control_path"] = {
                "proposals": m.proposals, "executed": m.executed, "blocked": m.blocked,
                "approvals_requested": m.approvals_requested, "rolled_back": m.rolled_back,
                "command_service_writes": len(self.run.change_log),
            }  # fmt: skip
        return out


@dataclass
class WhatIfResult:
    """Everything one what-if produced."""

    spec: WhatIfSpec
    lowest_fidelity: str
    preflight: dict[str, Any]
    policy: dict[str, Any]
    branches: dict[str, BranchResult]
    start_state_hashes: dict[str, str]
    comparison: dict[str, dict[str, Any]]

    def series(self) -> dict[str, list[dict[str, JsonValue]]]:
        """Return the fifteen-minute series of every branch that ran."""
        return {name: b.series for name, b in self.branches.items() if b.available}

    def summary(self) -> dict[str, Any]:
        """Return the result as JSON: request, preflight, branches, savings, violations."""
        branches = {name: b.summary() for name, b in self.branches.items()}
        ran = {n: b for n, b in self.branches.items() if b.available}
        statements = [*STATEMENTS, *WHATIF_STATEMENTS]
        if self.spec.energy_price is not None:
            statements.append(
                f"Cost is the facility kWh saved times {self.spec.energy_price.per_kwh:g} "
                f"{self.spec.energy_price.currency}/kWh as given in the request; it is not "
                "extrapolated beyond the run."
            )
        scenario = load_whatif_scenario(self.spec.scenario)
        duration = self.spec.duration_s or scenario.duration_s
        return {
            "request": self.spec.model_dump(mode="json"),
            "request_hash": self.spec.hash(),
            "scenario": {"id": scenario.id, "title": scenario.title},
            "duration_s": min(duration, scenario.duration_s),
            "shortened": duration < scenario.duration_s,
            "lowest_fidelity": self.lowest_fidelity,
            "start_state_hashes": dict(self.start_state_hashes),
            "preflight": self.preflight,
            "policy": self.policy,
            "branches": branches,
            "savings_against_baseline": self.comparison,
            "violations": {
                "physical": {"by_branch": {n: b.physical for n, b in ran.items()}},
                "governance": {
                    "by_branch": {
                        n: dict(b.governance or {}) for n, b in ran.items() if not b.hypothetical
                    },
                    "not_applicable": [n for n, b in ran.items() if b.hypothetical],
                },
            },  # fmt: skip
            "statements": statements,
        }


def _measured(branch: BranchResult, run: ScenarioRun, meter: Meter) -> None:
    result = run.run()
    branch.run = result
    branch.gate, branch.agent = result.gate, result.agent
    branch.energy = meter.energy(result.metrics)
    branch.physical = physical_violations(
        result.metrics, min_tes_charge_pct=meter.min_tes_charge_pct, max_pod_c=meter.max_pod_c
    )
    branch.governance = None if branch.hypothetical else governance_violations(result.metrics)
    branch.series = meter.series


def _governed_outcome(found: Study, spec: WhatIfSpec, branch: BranchResult) -> dict[str, Any]:
    assert branch.run is not None
    final = branch.final_values[found.tags[0]]
    reached = abs(final - spec.change.target) <= EPS
    remora = sorted({
        str(reason) for record in branch.run.records
        for reason in (record["reasons"] if isinstance(record["reasons"], list) else [])
        if str(reason).startswith("remora:")
    })  # fmt: skip
    applied = [r for r in branch.run.records if r["outcome"] in ("APPLIED", "ROLLED_BACK")]
    return {
        "target": spec.change.target,
        "final_value": final,
        "reached": reached,
        "steps_applied": len(applied),
        "stopped_because": stopped_because(branch.agent_log, reached),
        "remora_reasons": remora,
    }


def run_whatif(
    spec: WhatIfSpec,
    profile: Profile,
    contracts: ContractLibrary,
    *,
    gates: Mapping[str, GateFactory] | None = None,
    progress: Callable[[str], None] | None = None,
) -> WhatIfResult:
    """Play *spec* and return its result.

    *gates* are the installed gates by entry-point name (default: every gate
    under ``agentic_datacenter.gates``); the governed branch uses ``remora_governed`` and is
    reported as not run when that gate is missing or refuses to start.

    Raises:
        SpecError: If the request does not fit the contract or the plant.
        RuntimeError: If the branches do not start from the same state.
    """
    say = progress or (lambda _line: None)
    found = study(spec.change, contracts)
    keys = key_sets(profile)
    installed = load_gates() if gates is None else gates
    probe = start_run(spec, profile, contracts)
    start_hash = probe.world.kernel.state_hash()
    say("preflight")
    preflight = check(spec.change, found, probe.world, keys, start_hash)
    say("policy analysis")
    policy = policy_analysis.analyse(spec, found, probe.world, keys, start_hash)
    del probe

    branches: dict[str, BranchResult] = {}
    hashes: dict[str, str] = {}
    for name in spec.branches:
        branch = BranchResult(name, LABELS[name], hypothetical=name == "physical")
        branches[name] = branch
        meter = Meter()
        if name == "governed":
            factory = installed.get(GOVERNED_GATE)
            if factory is None:
                branch.available = False
                branch.unavailable_reason = f"gate {GOVERNED_GATE} is not installed (REMORA absent)"
                continue
            target = spec.change.target
            agent = GoalSeekingAgent(found.contract.id, found.argument, target)
            try:
                run = start_run(spec, profile, contracts, factory, "GOVERNED", lambda a=agent: a)
            except Exception as exc:  # a gate that refuses to start, e.g. a pin mismatch
                branch.available = False
                branch.unavailable_reason = f"gate {GOVERNED_GATE} did not start: {exc}"
                continue
            branch.operating_profile = "GOVERNED"
        else:
            run = start_run(spec, profile, contracts)
            branch.operating_profile = "BASELINE_RULES"
        branch.start_state_hash = hashes[name] = run.world.kernel.state_hash()
        if branch.start_state_hash != start_hash:
            raise RuntimeError(f"branch {name} does not start from the state of the others")
        hold = Hold(found.tags, spec.change.target) if name == "physical" else None
        if hold is not None:
            hold.apply(run.world)

            def observe(r: ScenarioRun, hold: Hold = hold, meter: Meter = meter) -> None:
                hold.reasserted += hold.apply(r.world)
                meter(r)

            run.observer = observe
        else:
            run.observer = meter
        say(f"branch {name}")
        _measured(branch, run, meter)
        branch.final_values = Hold(found.tags, spec.change.target).read(run.world)
        if hold is not None:
            branch.override = {
                "kind": "simulator-internal override of the module's I/O board",
                "tags": list(found.tags),
                "value": spec.change.target,
                "from_t_s": 0,
                "reasserted": hold.reasserted,
                "through_command_service": False,
            }
        if name == "governed":
            branch.agent_log = list(agent.log)
            branch.outcome = _governed_outcome(found, spec, branch)

    comparison: dict[str, dict[str, Any]] = {}
    base = branches["baseline"]
    for other, played in branches.items():
        if other != "baseline" and played.available:
            comparison[other] = compare(base.energy, played.energy, spec.energy_price)
    return WhatIfResult(
        spec=spec,
        lowest_fidelity=lowest_fidelity(profile),
        preflight=preflight,
        policy=policy,
        branches=branches,
        start_state_hashes=hashes,
        comparison=comparison,
    )
