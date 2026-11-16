"""REMORA's policy analysis of the change, beside the physics (ADR 0019, decision 5).

The only module of the package that reaches anything of REMORA, and only
through the binding's adapter, ``agentic_datacenter_remora.whatif``, imported when the
analysis is asked for. Without REMORA, or with a REMORA whose SDK has no
``what_if``, the result says so and nothing else happens.

The analysis is of the policy, not a decision: it grants nothing, proposes
nothing and writes nothing. Every fact that would change a verdict is tagged
with who could bring it about, and a fact only the deployment declares is
labelled as needing authorised reconfiguration, never offered as an option.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.gate import Proposal
from agentic_datacenter.scenarios.harness import World
from agentic_datacenter.whatif.models import WhatIfSpec
from agentic_datacenter.whatif.preflight import (
    Study,
    first_step,
    key_sets,
    snapshot_for,
    start_run,
    start_value,
    study,
)

RECONFIGURATION = "requires authorised reconfiguration"
WHO = {
    "deployment_fact": RECONFIGURATION,
    "proposal": "a different proposal: the call the agent chooses to make",
    "model_signal": "model output: cannot authorise anything on its own",
}
NOTE = (
    "REMORA's analysis of its own policy for this call (remora.sdk.what_if). Advisory: it "
    "grants nothing, no proposal is made and nothing is written. A fact marked "
    f"'{RECONFIGURATION}' is declared by the deployment and is not an option for the agent "
    "or the requester."
)


def unavailable(reason: str) -> dict[str, Any]:
    """Return the policy part of a result that has no analysis, and why."""
    return {"available": False, "reason": reason, "calls": [], "grants": "nothing", "note": NOTE}


def _levers(report: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Every lever that moves the verdict alone or is part of a minimal path, labelled."""
    found: dict[str, dict[str, Any]] = {}
    for effect in report.get("single_lever_effects", []):
        if effect["moves"]:
            found[effect["lever"]] = {
                "lever": effect["lever"], "kind": effect["kind"],
                "who": WHO.get(effect["kind"], effect["kind"]),
                "moves_alone_to": effect["action"], "in_minimal_path": False, "description": "",
            }  # fmt: skip
    for path in report.get("minimal_paths", []):
        for change in path["changes"]:
            entry = found.setdefault(change["lever"], {
                "lever": change["lever"], "kind": change["kind"],
                "who": WHO.get(change["kind"], change["kind"]), "moves_alone_to": None,
            })  # fmt: skip
            entry["in_minimal_path"] = True
            entry["description"] = change["description"]
            entry["field"], entry["before"], entry["after"] = (
                change["field"], change["before"], change["after"],
            )  # fmt: skip
    return [found[name] for name in sorted(found)]


def _plain(call: str, stage: Mapping[str, Any]) -> str:
    """One sentence on what a stage says, without offering a deployment fact as a choice."""
    report = stage["report"]
    now = str(report["current_action"]).upper()
    text = f"{call}, {stage['stage']}: REMORA's verdict is {now}"
    if report.get("hard_guard"):
        text += f"; hard guard {report['hard_guard']}"
    if report.get("already_at_target"):
        return text + "."
    goal = str(report["target"]).upper()
    # A search the evaluation budget stopped has not shown that what it did not find
    # does not exist: a negative is then unknown, never "none" or "every".
    # A report that does not say its search finished is read as one that did not.
    complete = bool(report.get("search", {}).get("exhausted", False))
    stopped = "the search was stopped by its evaluation budget"
    paths = report.get("minimal_paths") or []
    agent = [p for p in paths if "deployment_fact" not in p["kinds"]]
    # The smallest path of the agent's own may be larger than the smallest path of all,
    # and a path of model signals alone is one of the agent's own.
    alone = (
        agent[0] if agent else report.get("without_deployment") or report.get("model_signals_alone")
    )
    if alone:
        levers = " + ".join(alone["levers"])
        by = "model signals alone" if alone["kinds"] == ["model_signal"] else "a different proposal"
        text += f"; {by} would reach {goal} ({levers})"
        if not complete:
            text += f"; {stopped}, so what it did not find is unknown"
    elif not paths and complete:
        text += "; no change set within the search bound reaches the target"
    elif not paths:
        text += (
            f"; {stopped} before a change set was found, so whether one reaches {goal} is unknown"
        )
    elif complete:
        text += f"; every path to {goal} needs a deployment fact ({RECONFIGURATION})"
    else:
        text += (
            f"; the change sets found need a deployment fact ({RECONFIGURATION}); {stopped}, "
            f"so whether a different proposal alone would reach {goal} is unknown"
        )
    return text + "."


def analyse(spec: WhatIfSpec, found: Study, world: World, keys: Mapping[str, tuple[str, ...]],
            start_state_hash: str) -> dict[str, Any]:  # fmt: skip
    """Return the policy analysis of the change as one call and of its first contract step."""
    if not spec.policy.enabled:
        return unavailable("not requested (policy.enabled is false)")
    try:
        from agentic_datacenter_remora import whatif as adapter
    except ImportError:
        return unavailable(
            "REMORA is not installed (no agentic-datacenter-remora); the policy analysis is skipped"
        )
    reason = adapter.unavailable_reason()
    if reason is not None:
        return unavailable(reason)
    start = start_value(found, world, spec.change)
    values = {"as_one_call": spec.change.target}
    step = first_step(start, spec.change.target, found.max_step)
    if step != spec.change.target:
        values["first_step"] = step
    calls = []
    for label, value in values.items():
        arguments = {found.argument: value}
        proposal = Proposal(f"whatif-{label}", found.contract.id, arguments)
        out = adapter.analyse(
            proposal,
            snapshot_for(found, value, world, keys),
            max_depth=spec.policy.max_depth,
            max_evaluations=spec.policy.max_evaluations,
        )
        stages = list(out["stages"])
        for stage in stages:
            stage["levers"] = _levers(stage["report"])
            stage["plain"] = _plain(label, stage)
        calls.append({
            "call": label, "contract_id": found.contract.id, "arguments": arguments,
            "unformable": out["unformable"], "stages": stages,
        })  # fmt: skip
    return {
        "available": True,
        "remora": adapter.identity(),
        "target": "accept",
        "start_state_hash": start_state_hash,
        "calls": calls,
        "grants": "nothing",
        "note": NOTE,
    }


def run_policy(spec: WhatIfSpec, profile: Profile, contracts: ContractLibrary) -> dict[str, Any]:
    """Build the start state of *spec* and return the policy analysis of its change."""
    found = study(spec.change, contracts)
    if not spec.policy.enabled:
        return unavailable("not requested (policy.enabled is false)")
    run = start_run(spec, profile, contracts)
    digest = run.world.kernel.state_hash()
    return analyse(spec, found, run.world, key_sets(profile), digest)
