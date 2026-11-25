"""Several governance systems at once, as in a pilot: the strictest verdict decides (ADR 0036).

``ADC_CHAIN_FILE`` names a JSON file::

    {"name": "pilot", "members": [
        {"name": "policy", "command": "python examples/command-gate/adapter.py"},
        {"name": "identity", "url": "http://127.0.0.1:8787", "context": true},
        {"name": "baseline", "gate": "static_allowlist"}
    ]}

A member is a command, a service over HTTP, or an installed gate by its entry
point. Every member is asked about every proposal, each with its own session,
correlation and receipts. The chain's verdict is the strictest of theirs:
``DENY`` before ``ABSTAIN`` before ``VERIFY`` before ``ALLOW``. A ``VERIFY``
asks for as many people as the member that asks for most. An ``ALLOW`` stands
only when every member allowed the same writes. The decision record keeps
each member's verdict, reasons and correlation in ``gate_detail.members``.

The members decide; none executes. A member that authorizes execution itself
(the REMORA gates under ``GOVERNED``) is refused as a member. Every member is
given the premise ``authority(<principal>, <contract>)``.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping
from dataclasses import replace
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.governance.bindings.http_gate import (
    CommandGate,
    HttpGate,
    HttpGateConfigError,
)
from agentic_datacenter.governance.envelope_ref import DECISION_TTL_MS, decision_ref
from agentic_datacenter.governance.gate import (
    AuthenticatedActor,
    Decision,
    GovernanceGate,
    Outcome,
    PremiseSnapshot,
    Proposal,
    Verdict,
)
from agentic_datacenter.governance.interop import EPOCH, GATE_DETAIL_KEPT

#: Strictest first.
ORDER = (Verdict.DENY, Verdict.ABSTAIN, Verdict.VERIFY, Verdict.ALLOW)
#: Hooks of a gate that authorizes execution itself; such a gate is not a member.
EXECUTING_HOOKS = ("execute", "approve", "reject", "resolve_unknown")


class ChainConfigError(ValueError):
    """The chain file is missing, malformed, or names a member that cannot be one."""


def _member(spec: Mapping[str, Any], contracts: object, epoch: str) -> GovernanceGate:
    name = str(spec.get("name") or "")
    if not name:
        raise ChainConfigError("every member needs a name")
    options: dict[str, Any] = {
        "name": name,
        "timeout_s": float(spec.get("timeout_s", 10)),
        "stateful": bool(spec.get("stateful", False)),
        "wants_context": bool(spec.get("context", False)),
        "epoch": epoch,
    }
    kinds = [k for k in ("command", "url", "gate") if k in spec]
    if len(kinds) != 1:
        raise ChainConfigError(f"member {name}: give exactly one of command, url and gate")
    if "command" in spec:
        return CommandGate(str(spec["command"]), **options)
    if "url" in spec:
        allow_remote = bool(spec.get("allow_remote", False))
        return HttpGate(str(spec["url"]), allow_remote=allow_remote, **options)
    found = {e.name: e for e in entry_points(group="agentic_datacenter.gates")}
    gate_name = str(spec["gate"])
    if gate_name not in found or gate_name == "chain_gate":
        raise ChainConfigError(f"member {name}: no installed gate {gate_name!r}")
    made = found[gate_name].load()(contracts)
    if any(callable(getattr(made, hook, None)) for hook in EXECUTING_HOOKS):
        raise ChainConfigError(
            f"member {name}: {gate_name} authorizes execution itself and cannot be a member"
        )
    return made  # type: ignore[no-any-return]


class ChainGate:
    """A ``GovernanceGate`` that asks every member and takes the strictest verdict."""

    def __init__(
        self,
        members: Mapping[str, GovernanceGate],
        name: str = "chain_gate",
        profile: str = "DECISION_ONLY",
    ) -> None:
        """Bind the members, in the order given."""
        if not members:
            raise ChainConfigError("a chain needs at least one member")
        self.name, self.profile = name, profile
        self.members = dict(members)
        #: The control path sends a sample of the plant if any member wants one.
        self.wants_context = any(getattr(m, "wants_context", False) for m in members.values())
        epochs = {str(getattr(m, "context_epoch", EPOCH)) for m in members.values()}
        self.context_epoch = epochs.pop() if len(epochs) == 1 else EPOCH
        self.restorable = all(getattr(m, "restorable", True) for m in members.values())
        self._refs: dict[str, list[tuple[str, str]]] = {}

    @property
    def failures(self) -> list[str]:
        """Why a member failed to give a usable answer, each with the member's name."""
        return [f"{n}: {f}" for n, m in self.members.items() for f in getattr(m, "failures", [])]

    def evaluate(
        self, proposal: Proposal, premises: PremiseSnapshot, actor: AuthenticatedActor
    ) -> Decision:
        """Ask every member; the strictest verdict decides."""
        decisions = {
            # A member that did not ask for the plant's context is not sent it.
            n: m.evaluate(
                proposal,
                premises if getattr(m, "wants_context", False) else replace(premises, context=None),
                actor,
            )
            for n, m in self.members.items()
        }
        verdict = min((d.verdict for d in decisions.values()), key=ORDER.index)
        # A failed service keeps the words its reason starts with, so it is counted as one.
        reasons = tuple(
            f"{r} (member {n})" if r.startswith("gate service ") else f"{n}: {r}"
            for n, d in decisions.items()
            for r in d.reasons
        ) or ("no member gave a reason",)
        writes = premises.writes if verdict is Verdict.ALLOW else ()
        if verdict is Verdict.ALLOW and any(
            set(d.bounded_writes) != set(premises.writes) for d in decisions.values()
        ):
            verdict, writes = Verdict.DENY, ()
            reasons += ("chain: the members did not allow the same writes",)
        approvers = max(
            (d.required_approvers for d in decisions.values() if d.verdict is Verdict.VERIFY),
            default=0,
        )
        approvers = max(approvers, 1) if verdict is Verdict.VERIFY else 0
        codes: list[str] = []
        for d in decisions.values():
            codes += [c for c in d.reason_codes if c not in codes]
        members: list[JsonValue] = []
        for n, d in decisions.items():
            member: dict[str, JsonValue] = {
                "name": n, "verdict": d.verdict.value, "reasons": list(d.reasons),
                "decisive": d.verdict is verdict,
            }  # fmt: skip
            member.update({k: d.detail[k] for k in GATE_DETAIL_KEPT if k in d.detail})
            members.append(member)
        ref = decision_ref(
            self.name, proposal.proposal_id, proposal.contract_id, verdict.value,
            [[w.tag, w.value] for w in writes], list(reasons), premises.time_ms,
        )  # fmt: skip
        self._refs[ref] = [(n, d.decision_ref) for n, d in decisions.items()]
        return Decision(
            verdict,
            ref,
            proposal.contract_id,
            writes,
            premises.time_ms + DECISION_TTL_MS,
            ref[-12:],
            reasons,
            required_approvers=approvers,
            escalated=any(d.escalated for d in decisions.values()),
            detail={"members": members},
            reason_codes=tuple(codes),
        )

    def record_outcome(self, decision_ref: str, outcome: Outcome) -> None:
        """Tell every member what became of its own decision."""
        for name, ref in self._refs.get(decision_ref, []):
            self.members[name].record_outcome(ref, outcome)


def from_file(path: Path, contracts: object = None) -> ChainGate:
    """Build the chain a chain file describes.

    Raises:
        ChainConfigError: If the file cannot be read or describes no valid chain.
    """
    try:
        spec = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ChainConfigError(f"{path}: {exc}") from exc
    if not isinstance(spec, dict) or not isinstance(spec.get("members"), list):
        raise ChainConfigError(f"{path}: expected an object with a list of members")
    epoch = str(spec.get("epoch", os.environ.get("ADC_GATE_EPOCH", EPOCH)))
    members: dict[str, GovernanceGate] = {}
    for entry in spec["members"]:
        if not isinstance(entry, dict):
            raise ChainConfigError(f"{path}: every member is an object")
        try:
            made = _member(entry, contracts, epoch)
        except HttpGateConfigError as exc:
            raise ChainConfigError(f"member {entry.get('name')}: {exc}") from exc
        if made.name in members or str(entry["name"]) in members:
            raise ChainConfigError(f"two members are named {entry['name']}")
        members[str(entry["name"])] = made
    return ChainGate(members, name=str(spec.get("name", "chain_gate")))


def create(contracts: object) -> ChainGate:
    """Build the chain of ``ADC_CHAIN_FILE`` for a benchmark run."""
    path = os.environ.get("ADC_CHAIN_FILE", "")
    if not path:
        raise ChainConfigError("ADC_CHAIN_FILE is not set")
    return from_file(Path(path), contracts)
