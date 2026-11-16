"""The contract preflight: does the change fit its contract at the start state? (ADR 0019).

Read with the same code the control path uses (``build_snapshot``), at the
instant every branch starts from, and reported apart from the physics. It
answers what the contract's own published terms say: range, step, rate,
cumulative limit and the premises the change would need. It grants nothing
and writes nothing.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from typing import Any

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import Contract, ContractLibrary
from agentic_datacenter.governance.gate import PremiseSnapshot
from agentic_datacenter.governance.premises import PremiseReader, build_snapshot
from agentic_datacenter.scenarios.harness import ScenarioRun, World
from agentic_datacenter.supervisory.overview import Overview
from agentic_datacenter.whatif.models import Change, SpecError, WhatIfSpec, load_whatif_scenario

EPS = 1e-9


@dataclass(frozen=True)
class Study:
    """The contract a change is about, and the points it writes."""

    contract: Contract
    argument: str
    tags: tuple[str, ...]

    @property
    def max_step(self) -> float | None:
        """The largest step of the first write, if the contract limits it."""
        bounds = self.contract.writes[0].bounds
        return bounds.max_step if bounds is not None else None


def study(change: Change, contracts: ContractLibrary) -> Study:
    """Check that *change* is about a contract a what-if can play.

    That is a contract with one numeric argument that every write takes, with
    bounds on the first write and no point chosen by another argument.

    Raises:
        SpecError: Naming what does not fit.
    """
    contract = contracts.get(change.contract_id)
    if contract is None:
        raise SpecError(f"no contract {change.contract_id} in the library")
    spec = contract.arguments.get(change.argument)
    if spec is None or spec.type != "number":
        raise SpecError(
            f"{contract.id}: {change.argument} is not a number argument of the contract; a "
            "what-if needs one number that every write takes"
        )
    if len(contract.arguments) != 1 or any(w.value != change.argument for w in contract.writes):
        raise SpecError(f"{contract.id}: not every write takes {change.argument}")
    if any("{" in w.tag for w in contract.writes) or contract.writes[0].bounds is None:
        raise SpecError(f"{contract.id}: the written points must be fixed and bounded")
    return Study(contract, change.argument, tuple(w.tag for w in contract.writes))


def start_run(
    spec: WhatIfSpec,
    profile: Profile,
    contracts: ContractLibrary,
    make_gate: Any = None,
    operating_profile: str = "BASELINE_RULES",
    make_agent: Any = None,
) -> ScenarioRun:
    """Build one run of the request's scenario and seed, warmed up to its start."""
    scenario = load_whatif_scenario(spec.scenario)
    return ScenarioRun(
        scenario,
        profile,
        make_gate or (lambda _library: NullGate()),
        operating_profile,
        make_agent,
        spec.seed,
        contracts,
        spec.duration_s,
    )


def snapshot_for(
    found: Study, value: float, world: World, key_sets: Mapping[str, tuple[str, ...]]
) -> PremiseSnapshot:
    """Return what the control path would establish now for the contract at *value*."""
    reader = PremiseReader(world.points, Overview(world.points, world.path.notes))
    return build_snapshot(
        found.contract,
        {found.argument: value},
        reader,
        world.points,
        key_sets,
        (),
        world.kernel.clock.now_ms,
    )


def first_step(start: float, target: float, max_step: float | None) -> float:
    """Return the value of the first contract step from *start* toward *target*."""
    delta = target - start
    if max_step is None or abs(delta) <= max_step + EPS:
        return target
    return round(start + math.copysign(max_step, delta), 9)


def start_value(found: Study, world: World, change: Change) -> float:
    """Return the present value of the first written point, checked against the request.

    Raises:
        SpecError: If it is not a number, or not the value the request expected.
    """
    value = world.points.read(found.tags[0]).value
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise SpecError(f"{found.tags[0]} is not a number")
    if change.expected_start is not None and abs(float(value) - change.expected_start) > EPS:
        raise SpecError(
            f"{found.tags[0]} is {float(value):g} at the start, not the expected "
            f"{change.expected_start:g}"
        )
    return float(value)


def check(
    change: Change,
    found: Study,
    world: World,
    key_sets: Mapping[str, tuple[str, ...]],
    start_state_hash: str,
) -> dict[str, Any]:
    """Return the preflight of *change* against its contract in *world*, as it stands."""
    contract, start = found.contract, start_value(found, world, change)
    target, delta = change.target, change.target - start
    max_step = found.max_step
    whole = snapshot_for(found, target, world, key_sets)
    step_value = first_step(start, target, max_step)
    first = snapshot_for(found, step_value, world, key_sets)
    checks: list[dict[str, Any]] = []

    outside = [e for e in whole.bound_errors if e.startswith("range:")]
    checks.append({
        "name": "range", "passed": not outside,
        "detail": "; ".join(outside) or "inside the bounds of every written point",
    })  # fmt: skip
    steps = 0 if abs(delta) <= EPS else 1
    if max_step is not None and steps:
        steps = math.ceil(abs(delta) / max_step - EPS)
    too_far = [e for e in whole.bound_errors if e.startswith("step:")]
    checks.append({
        "name": "step", "passed": not too_far,
        "detail": (
            f"a move of {abs(delta):g} is more than the step of {max_step:g}; "
            f"{steps} steps are needed" if too_far else "one step is enough"
        ),
    })  # fmt: skip
    rate = contract.limits.rate
    per_hour = rate.max_per_hour if rate is not None else None
    earliest = float((steps - 1) // per_hour) if per_hour and steps else 0.0
    checks.append({
        "name": "rate", "passed": not first.limit_errors or not any(
            e.startswith("rate:") for e in first.limit_errors),
        "detail": (
            f"at most {per_hour} calls an hour; {steps} steps can end at the earliest "
            f"{earliest:g} h after the first" if per_hour else "no rate limit"
        ),
    })  # fmt: skip
    cumulative = contract.limits.cumulative
    limit = cumulative.max_total_delta if cumulative is not None else None
    window = float(cumulative.window_h) if cumulative is not None else None
    within = limit is None or abs(delta) <= limit + EPS
    bounds = contract.writes[0].bounds
    assert bounds is not None
    reach = target
    if limit is not None and not within:
        reach = start + math.copysign(limit, delta)
    reach = min(bounds.max, max(bounds.min, reach))
    checks.append({
        "name": "cumulative", "passed": within,
        "detail": (
            "no cumulative limit" if limit is None else
            f"a move of {abs(delta):g} in {window:g} h is "
            + ("within" if within else "more than") + f" the limit of {limit:g}"
            + ("" if within else f"; at most {reach:g} is reachable in one window")
        ),
    })  # fmt: skip
    premises = [asdict(p) for p in first.premises]
    holding = all(p.holds is True for p in first.premises)
    failing = [p.expr for p in first.premises if p.holds is not True]
    checks.append({
        "name": "premises", "passed": holding,
        "detail": "every premise holds at the start" if holding
        else "not holding or not established: " + "; ".join(failing),
    })  # fmt: skip
    passed = {c["name"]: c["passed"] for c in checks}
    if steps == 0:
        verdict = "no_change"
    elif not passed["range"]:
        verdict = "outside_bounds"
    elif not passed["premises"]:
        verdict = "premises_do_not_hold"
    elif not passed["cumulative"]:
        verdict = "not_reachable_within_window"
    elif not passed["step"]:
        verdict = "reachable_in_steps"
    else:
        verdict = "fits_as_one_call"
    return {
        "contract_id": contract.id,
        "argument": found.argument,
        "tags": list(found.tags),
        "start_value": start,
        "target": target,
        "delta": delta,
        "checks": checks,
        "steps_needed": steps,
        "first_step_value": step_value,
        "max_step": max_step,
        "rate_per_hour": per_hour,
        "earliest_last_step_h": earliest,
        "cumulative_limit": limit,
        "window_h": window,
        "reachable_within_window": within and passed["range"],
        "max_reachable_in_window": reach,
        "premises": premises,
        "verdict": verdict,
        "start_state_hash": start_state_hash,
        "grants": "nothing",
        "note": (
            "The contract's own published terms, read at the start state with the control "
            "path's code. Advisory: nothing is proposed, decided or written."
        ),
    }


def run_preflight(spec: WhatIfSpec, profile: Profile, contracts: ContractLibrary) -> dict[str, Any]:
    """Build the start state of *spec* and return the preflight of its change."""
    found = study(spec.change, contracts)
    run = start_run(spec, profile, contracts)
    digest = run.world.kernel.state_hash()
    return check(spec.change, found, run.world, key_sets(profile), digest)


def key_sets(profile: Profile) -> dict[str, tuple[str, ...]]:
    """Return the profile's key sets as the control path holds them."""
    return {name: tuple(values) for name, values in profile.key_sets.items()}
