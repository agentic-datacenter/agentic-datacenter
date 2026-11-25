"""One action, followed end to end: who did what, when, and who saw it (ADR 0038).

For each proposal of a run the trace gives, in the order they happened: the
proposal, the gate's decision, every approval and refusal, every change to the
proposer's mandate while the step was open, the check made before anything
was written, each command sent to the plant, and the outcome. Each link says
who observed it: the control path, the gate, the mandate register, an operator
or the command service.

Three things a reader must be able to tell apart are given as separate states,
never folded into one:

- ``receipt``: ``none`` when the gate gave no receipt, ``given`` when it did;
- ``signature``: ``not_checked``. Nothing here checks a signature yet (ADR 0037);
- ``physical``: what is known of the write at the plant: ``no_write``,
  ``acknowledged`` (accepted by the command service, not an independent
  read-back), ``resolved_by_read_back`` (unanswered, then established by
  reading the plant) or ``not_observed`` (unanswered and never established).

It is made from the decision records, the command service's change log and
the scenario's mandate changes, all of which are in the evidence bundle, so
anyone can make it again. It holds nothing that differs between two
executions of the same run.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from agentic_datacenter.scenarios.scenario import Scenario

TRACE_SCHEMA = "agentic_datacenter.action_trace/1"


def _mandate_changes(scenario: Scenario) -> list[dict[str, Any]]:
    changes = []
    for event in scenario.timeline:
        if event.authority is not None:
            held = event.authority.contracts
            changes.append({
                "at_ms": (scenario.warmup_s + event.at_s) * 1000,
                "principal": event.authority.principal,
                "contracts": held if held == "all" else list(held),
                "by": event.authority.by, "reason": event.authority.reason,
            })  # fmt: skip
    return changes


def _physical(record: Mapping[str, Any], commands: Sequence[Mapping[str, Any]]) -> str:
    if record.get("outcome") == "UNKNOWN":
        return "not_observed"
    if record.get("was_unknown"):
        return "resolved_by_read_back"
    if any(c["accepted"] for c in commands) and record.get("outcome") in ("APPLIED", "ROLLED_BACK"):
        return "acknowledged"
    return "no_write"


def _stopped_by(record: Mapping[str, Any], trace: Mapping[str, Any]) -> str | None:
    outcome, verdict = record.get("outcome"), record.get("verdict")
    if outcome in ("APPLIED", "ROLLED_BACK", "UNKNOWN"):
        return None
    if trace.get("mandate_at_check") is False:
        return "control path: the mandate had ended when the approval came in"
    if trace.get("rejections"):
        return "operator"
    if verdict in ("DENY", "ABSTAIN"):
        return "gate"
    if verdict == "VERIFY":
        return "still waiting for approval" if outcome == "NOT_EXECUTED" else "approval"
    if outcome == "REJECTED":
        return "control path or command service"
    return None


def action_trace(
    records: Sequence[Mapping[str, Any]],
    change_log: Sequence[Mapping[str, Any]],
    scenario: Scenario,
) -> list[dict[str, Any]]:
    """Return one entry per proposal: its links in time order, and its three states."""
    mandates = _mandate_changes(scenario)
    out = []
    for record in records:
        pid, principal = str(record["proposal_id"]), str(record["principal"])
        trace = record.get("trace") if isinstance(record.get("trace"), Mapping) else {}
        assert isinstance(trace, Mapping)
        start = int(record["time_ms"])
        end = int(trace.get("finished_at_ms", start))
        commands = [c for c in change_log if str(c.get("reason", "")).endswith(f"({pid})")]
        links: list[dict[str, Any]] = [
            {"step": "proposal", "at_ms": start, "by": principal, "observed_by": "control path",
             "contract": record["contract_id"], "arguments": record.get("arguments"),
             "rationale": record.get("rationale", "")},
        ]  # fmt: skip
        if record.get("verdict") is not None:
            links.append({
                "step": "decision", "at_ms": start, "by": record.get("gate"),
                "observed_by": "gate", "verdict": record["verdict"],
                "reasons": list(record.get("reasons") or []),
                "decision_ref": record.get("decision_ref"),
                "required_approvers": record.get("required_approvers", 0),
            })  # fmt: skip
        for kind in ("approvals", "refusals", "rejections"):
            for entry in trace.get(kind, []):
                links.append({"step": kind[:-1], "observed_by": "control path", **dict(entry)})
        for change in mandates:
            if change["principal"] == principal and start < change["at_ms"] <= end:
                links.append({"step": "mandate_change", "observed_by": "mandate register",
                              **change})  # fmt: skip
        if "checked_at_ms" in trace:
            links.append({
                "step": "check_before_write", "at_ms": trace["checked_at_ms"],
                "observed_by": "control path", "mandate_held": trace.get("mandate_at_check"),
            })  # fmt: skip
        for c in commands:
            links.append({
                "step": "command", "at_ms": c["time_ms"], "observed_by": "command service",
                "tag": c["tag"], "old": c.get("old"), "new": c.get("new"),
                "accepted": c["accepted"], "code": c.get("code"), "by": c.get("actor"),
            })  # fmt: skip
        links.append({
            "step": "outcome", "at_ms": end, "observed_by": "control path",
            "status": record.get("outcome"), "detail": record.get("outcome_detail", ""),
        })  # fmt: skip
        links.sort(key=lambda link: (int(link.get("at_ms") or 0), _ORDER.index(link["step"])))
        detail = record.get("gate_detail")
        given = isinstance(detail, Mapping) and (
            "service_receipt" in detail or "service_decision_id" in detail
        )
        out.append({
            "schema": TRACE_SCHEMA, "proposal_id": pid, "contract": record["contract_id"],
            "principal": principal, "gate": record.get("gate"),
            "receipt": "given" if given else "none", "signature": "not_checked",
            "physical": _physical(record, commands),
            "stopped_by": _stopped_by(record, trace), "links": links,
        })  # fmt: skip
    return out


_ORDER = (
    "proposal", "decision", "approval", "refusal", "rejection", "mandate_change",
    "check_before_write", "command", "outcome",
)  # fmt: skip


def render_trace(entries: Sequence[Mapping[str, Any]], scenario: Scenario) -> str:
    """Return the trace as Markdown, one section per action, for a reader to follow."""
    warmup = scenario.warmup_s * 1000

    def when(ms: Any) -> str:
        seconds = (int(ms or 0) - warmup) // 1000
        return f"{seconds // 60:d}:{seconds % 60:02d}"

    lines = [
        f"# What became of each action in {scenario.id}",
        "",
        "Times are minutes into the scenario. Each line says who observed it. "
        "`receipt`, `signature` and `physical` are kept apart: a missing receipt, a signature "
        "that was not checked and a write nobody observed at the plant are three different "
        "things.",
        "",
    ]
    for entry in entries:
        lines += [
            f"## {entry['proposal_id']}: `{entry['contract']}`",
            "",
            f"Receipt: {entry['receipt']}. Signature: {entry['signature']}. "
            f"At the plant: {entry['physical']}."
            + (f" Stopped by: {entry['stopped_by']}." if entry["stopped_by"] else ""),
            "",
            "| Time | Step | What | Observed by |",
            "| ---: | --- | --- | --- |",
        ]
        for link in entry["links"]:
            lines.append(
                f"| {when(link.get('at_ms'))} | {link['step']} | {_what(link)} | "
                f"{link['observed_by']} |"
            )
        lines.append("")
    return "\n".join(lines)


def _what(link: Mapping[str, Any]) -> str:
    step = link["step"]
    if step == "proposal":
        return f"{link['by']} proposes it: {link.get('rationale') or ''}".strip()
    if step == "decision":
        return f"{link['by']}: {link['verdict']}"
    if step in ("approval", "refusal", "rejection"):
        return f"{link['by']}" + (f": {link['why']}" if link.get("why") else "")
    if step == "mandate_change":
        return f"mandate now {link['contracts'] or 'none'}, by {link['by']}"
    if step == "check_before_write":
        return "mandate held" if link["mandate_held"] else "mandate no longer held"
    if step == "command":
        state = "accepted" if link["accepted"] else f"refused ({link.get('code')})"
        return f"{link['tag']}: {link.get('old')} → {link.get('new')}, {state}"
    return f"{link.get('status')} {link.get('detail') or ''}".strip()
