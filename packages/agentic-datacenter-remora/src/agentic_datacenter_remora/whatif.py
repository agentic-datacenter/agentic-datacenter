"""REMORA's policy what-if on a Agentic-Datacenter proposal (ADR 0019). Advisory: it grants nothing.

``remora.sdk.what_if`` answers, for one observation, which verdict REMORA's
policy gives it, which hard guard applies and which smallest sets of facts
would change the verdict. A proposal meets REMORA twice on the governed path,
so it is analysed twice:

- ``pure_decision``: the observation this binding decides on in every profile
  (:func:`agentic_datacenter_remora.binding.observe`), under the library engine, exactly as
  :class:`agentic_datacenter_remora.binding.RemoraGate` asks ``evaluate_policy``. Under
  ``GOVERNED`` a proposal this stage abstains on never reaches the service.
- ``execution_service``: Agentic-Datacenter's reconstruction of the observation REMORA's
  execution API builds on its registry-only path from the compiled tool
  metadata (risk tier, action type, the downgrade-only schema and rollback
  facts, the two bounded-write facts the server sets for a signed, metered
  tool), under the engine flags the embedded service is configured with
  (``agentic_datacenter_remora.governed``). It is not read from the service.

``what_if`` reached ``remora.sdk`` with REMORA PR #1236 and is not in the
pinned commit, so it is looked up at run time and its absence is reported, not
raised as an import error. Nothing here calls the service, issues a token or
writes anything.

The search shares one evaluation budget between its parts and reports one flag
for all of them, ``search.exhausted``. When the budget stopped the search, a
part that found nothing has not shown that nothing exists, yet REMORA's report
still says ``False`` and its text "cannot reach". Each stage therefore carries
``conclusions``, Agentic-Datacenter's reading of the report: a negative from a search that
was cut short is ``unknown``, and the text is written from that reading. What
was found stands either way; every path in the report was decided by the engine.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Any

import remora.sdk as sdk

from agentic_datacenter.governance.gate import PremiseSnapshot, Proposal
from agentic_datacenter_remora.binding import installed_commit, observe
from agentic_datacenter_remora.compile import ACTION_TYPE, DOMAIN, HIGH, LOW, TARGET, TENANT

#: The engine flags of the embedded execution service (``agentic_datacenter_remora.governed``):
#: REMORA_BOUNDED_WRITE_ACCEPT=1, REMORA_BOUNDED_WRITE_REQUIRE_INTENT=0, the rest unset.
SERVICE_ENGINE = {"bounded_write_accept": True, "bounded_write_intent_optional": True}
_SHOWN = (
    "risk_tier", "action_type", "target_environment", "schema_valid", "rollback_available",
    "toolspec_enforced", "cumulative_limit_metered", "trust_score", "phase",
)  # fmt: skip
#: Where the REMORA code the service observation mirrors lives, at the pin.
SERVICE_SOURCE = (
    "Agentic-Datacenter's reconstruction of the observation REMORA's execution API builds on its "
    "registry-only path (servers/execution_api.py: _registry_only_observation, "
    "_with_bounded_write_facts), from the compiled tool metadata; not read from the service"
)
YES, NO, UNKNOWN = "yes", "no", "unknown"


def unavailable_reason() -> str | None:
    """Return why the analysis cannot run with the installed REMORA, or None when it can."""
    if getattr(sdk, "what_if", None) is None or getattr(sdk, "EngineOptions", None) is None:
        commit = installed_commit() or "of unknown commit"
        return (
            f"the installed REMORA ({commit}) has no remora.sdk.what_if; it arrives with "
            "REMORA PR #1236 and is not in the pinned commit"
        )
    return None


def identity() -> dict[str, Any]:
    """Return what identifies the REMORA the analysis ran on, for the evidence."""
    return {"remora_commit": installed_commit(), "sdk_what_if": unavailable_reason() is None}


def _declared_tier(premises: PremiseSnapshot) -> str:
    """The REMORA tier the compiled tool metadata declares (``compile.risk_tier``)."""
    if premises.risk_tier in ("R0", "R1") and premises.rollback_available:
        return LOW
    return HIGH


def service_observation(proposal: Proposal, premises: PremiseSnapshot) -> Any:
    """Return the reconstruction of the observation REMORA's execution API would decide on."""
    first = premises.writes[0]
    arguments = {**dict(proposal.arguments), "target": f"whatif|{first.tag}"}
    observation = sdk.PolicyObservation.from_tool_call(
        name=proposal.contract_id,
        arguments=arguments,
        risk_tier=_declared_tier(premises),
        domain=DOMAIN,
        action_type=ACTION_TYPE,
        target_environment=TARGET,
        trust_score=None,
        phase=None,
        evidence_action=None,
        evidence_confidence=None,
        schema_valid=not premises.bound_errors,
        rollback_available=premises.rollback_available,
        session_id=TENANT,
    )
    return dataclasses.replace(observation, toolspec_enforced=True, cumulative_limit_metered=True)


def _unformable(premises: PremiseSnapshot) -> list[str]:
    """What keeps a proposal from being formed at all (as ``RemoraGate.evaluate`` refuses it)."""
    problems: list[str] = []
    if not premises.contract_known:
        problems.append("no such contract")
    elif premises.approval == "not_available":
        problems.append(f"risk tier {premises.risk_tier}: never automated")
    problems += list(premises.schema_errors)
    if not problems and not premises.writes:
        problems.append("nothing that can be executed")
    return problems


def conclusions(report: Mapping[str, Any]) -> dict[str, Any]:
    """Return what *report* establishes: ``yes``, ``no`` or ``unknown`` for each of its claims.

    A ``yes`` rests on a path the engine decided and holds whatever the budget.
    A path found by one part of the search counts for the claims it implies:
    model signals are among the agent's levers, and a path of the agent's own
    reaches the target, whether or not the search over all levers got as far.

    A ``no`` that rests on not finding something is given only when the whole
    space was covered (``search.exhausted``), and then means none within
    ``max_depth`` changes of the lever catalogue. The report has one flag for
    all parts of the search, so when it is not set every such negative is
    ``unknown``, including one from a part that may have finished. The one
    ``no`` a found path proves is ``deployment_facts_required`` when the agent
    can reach the target alone.
    """
    complete = bool(report["search"]["exhausted"])
    model = bool(report["confidence_can_lift"])
    agent = model or bool(report["agent_alone_can_reach"])
    reachable = agent or bool(report["reachable"])

    def claim(found: bool) -> str:
        return YES if found else NO if complete else UNKNOWN

    if agent:
        needs_deployment = NO
    elif report["minimal_paths"]:
        # Paths were found and none is the agent's alone: proved only by a complete search.
        needs_deployment = YES if complete else UNKNOWN
    else:
        needs_deployment = NO if complete else UNKNOWN
    return {
        "search_complete": complete,
        "max_depth": report["search"].get("max_depth"),
        "reachable": claim(reachable),
        "confidence_can_lift": claim(model),
        "agent_alone_can_reach": claim(agent),
        "deployment_facts_required": needs_deployment,
    }


def _cut_short_summary(report: Mapping[str, Any]) -> str:
    """Return the text of a report whose search the budget stopped: no "cannot reach"."""
    goal = str(report["target"]).upper()
    search = report["search"]
    reasons = ", ".join(report["current_reasons"]) or "no reason recorded"
    lines = [f"verdict now: {str(report['current_action']).upper()} ({reasons})"]
    if report["hard_guard"]:
        lines.append(f"hard guard: {report['hard_guard']}; no model signal can pass it")
    lines.append(
        f"search stopped by the evaluation budget ({search['evaluations']} of at most "
        f"{search['max_evaluations']} evaluations, depth {search['max_depth']}): "
        "what was not found is unknown, not impossible"
    )
    model = report["model_signals_alone"]
    # Model signals are among the agent's levers: a path of theirs is the agent's too.
    alone = report["without_deployment"] or model
    for label, path in (
        ("model signals alone", model),
        ("agent alone (proposal + model signals)", alone),
    ):
        if path is not None:
            lines.append(f"{label}: reach {goal} via " + " + ".join(path["levers"]))
        else:
            lines.append(f"{label}: unknown whether {goal} can be reached")
    paths = report["minimal_paths"]
    if paths:
        lines.append(
            f"change sets found reaching {goal}: {len(paths)} of size "
            f"{report['minimal_path_size']}; there may be more of that size"
        )
        lines += ["  " + " + ".join(path["levers"]) for path in paths]
    elif alone is not None:
        lines.append(
            f"{goal} can be reached (above); the smallest change set over all levers "
            "was not established"
        )
    else:
        lines.append(f"no change set reaching {goal} was found; unknown whether one exists")
    return "\n".join(lines)


def _stage(
    name: str,
    observation: Any,
    options: Any,
    engine: dict[str, Any],
    source: str,
    target: str,
    max_depth: int,
    max_evaluations: int,
) -> dict[str, Any]:
    analyse_policy: Any = getattr(sdk, "what_if")  # noqa: B009 - absent at the pinned commit
    report = analyse_policy(
        observation,
        target=target,
        max_depth=max_depth,
        max_evaluations=max_evaluations,
        engine_options=options,
    )
    as_dict = report.to_dict()
    read = conclusions(as_dict)
    return {
        "stage": name,
        "engine": engine,
        "observation_source": source,
        "observation": {field: getattr(observation, field, None) for field in _SHOWN},
        # REMORA's report as it came; its booleans are read through ``conclusions``.
        "report": as_dict,
        "conclusions": read,
        "summary": report.summary() if read["search_complete"] else _cut_short_summary(as_dict),
    }


def analyse(
    proposal: Proposal,
    premises: PremiseSnapshot,
    *,
    target: str = "accept",
    max_depth: int = 4,
    max_evaluations: int = 20_000,
) -> dict[str, Any]:
    """Return REMORA's policy what-if for *proposal* on the premises read for it.

    Raises:
        RuntimeError: If the installed REMORA has no ``remora.sdk.what_if``.
    """
    unformable = _unformable(premises)
    if unformable:
        return {"stages": [], "unformable": unformable}
    reason = unavailable_reason()
    if reason is not None:
        raise RuntimeError(reason)
    pure = _stage(
        "pure_decision", observe(proposal, premises), None, {"library_default": True},
        "the observation agentic_datacenter_remora.binding.observe builds; "
        "decided by evaluate_policy",
        target, max_depth, max_evaluations,
    )  # fmt: skip
    engine_options: Any = getattr(sdk, "EngineOptions")  # noqa: B009 - absent at the pin
    options = engine_options.execution_surface(**SERVICE_ENGINE)
    service = _stage(
        "execution_service", service_observation(proposal, premises), options,
        dataclasses.asdict(options), SERVICE_SOURCE, target, max_depth, max_evaluations,
    )  # fmt: skip
    # Under GOVERNED, a proposal the pure decision abstains on is not put to the service.
    service["reached_on_the_governed_path"] = pure["report"]["current_action"] != "abstain"
    return {"stages": [pure, service], "unformable": []}
