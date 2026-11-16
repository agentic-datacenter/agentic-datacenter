"""The gate adapter interface (SDD 9.2).

The agent can read and propose; only a gate can authorize; only the
Supervisory Command Service can write. This file is the seam between the
second and the third: a small, vendor-neutral interface that any governance
system can implement. Nothing here knows which gate is behind it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol, runtime_checkable

from agentic_datacenter.core.state import JsonValue


class Verdict(StrEnum):
    """What a gate says about a proposal."""

    ALLOW = "ALLOW"
    DENY = "DENY"
    VERIFY = "VERIFY"  # a human must approve
    ABSTAIN = "ABSTAIN"  # evidence is missing, stale or contradicted


@dataclass(frozen=True)
class AuthenticatedActor:
    """Who is proposing, as established by the credential on the conduit (INV-GOV-5).

    Attributes:
        principal: The identity bound to the credential.
        credential: How it was established, for the record.
    """

    principal: str
    credential: str


@dataclass(frozen=True)
class Proposal:
    """One contract instance submitted for a decision. It never names a raw tag write.

    Attributes:
        proposal_id: Assigned by the tool server.
        contract_id: The intent contract proposed.
        arguments: Its arguments.
        rationale: Free text from the agent. Stored; never evidence.
        claimed_actor: Who the agent says it is acting for. Stored as a claim only.
    """

    proposal_id: str
    contract_id: str
    arguments: Mapping[str, JsonValue]
    rationale: str = ""
    claimed_actor: str | None = None


@dataclass(frozen=True)
class PremiseResult:
    """One premise as the gate binding read it.

    ``holds`` is None when the premise could not be established: a point it
    needs is stale or of bad quality, or older than the premise allows.
    """

    expr: str
    holds: bool | None
    detail: str
    invariant: str = ""


@dataclass(frozen=True)
class BoundedWrite:
    """One concrete write a contract instance would make."""

    tag: str
    value: bool | int | float | str
    previous: bool | int | float | str


@dataclass(frozen=True)
class PremiseSnapshot:
    """Everything the binding established about a proposal before the gate decides.

    The binding reads all of it from the supervisory layer itself. Nothing in
    it comes from the agent.

    Attributes:
        time_ms: Gate time at which it was read.
        contract_known: The contract exists in the library.
        risk_tier: ``R0`` to ``R3``.
        approval: ``none``, ``one_operator``, ``two_person`` or ``not_available``.
        writes: The concrete writes, in order.
        schema_errors: Why the arguments do not fit the contract, if they do not.
        bound_errors: Writes outside the contract's bounds or step.
        limit_errors: Rate or cumulative limits the instance would exceed.
        premises: Each premise that applies to this instance.
        rollback_available: The contract declares a rollback.
        restore: Every write moves its point back toward the value it had
            before the agent's standing writes, in the contract's safe
            direction, and no further. Rate and cumulative limits do not
            apply to such a step (INV-GOV-8).
    """

    time_ms: int
    contract_known: bool
    risk_tier: str = "R3"
    approval: str = "not_available"
    writes: tuple[BoundedWrite, ...] = ()
    schema_errors: tuple[str, ...] = ()
    bound_errors: tuple[str, ...] = ()
    limit_errors: tuple[str, ...] = ()
    premises: tuple[PremiseResult, ...] = ()
    rollback_available: bool = False
    restore: bool = False


@dataclass(frozen=True)
class Decision:
    """A gate's decision on one proposal."""

    verdict: Verdict
    decision_ref: str
    contract_id: str
    bounded_writes: tuple[BoundedWrite, ...] = ()
    expires_at_ms: int = 0
    single_use_nonce: str = ""
    reasons: tuple[str, ...] = ()
    required_approvers: int = 0
    escalated: bool = False
    detail: Mapping[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True)
class Outcome:
    """What became of an authorized proposal: applied, rejected, rolled back or unknown."""

    status: str
    detail: str = ""


OUTCOMES = ("APPLIED", "REJECTED", "ROLLED_BACK", "UNKNOWN", "NOT_EXECUTED")


class GateRefusal(Exception):  # noqa: N818 - a refusal is an answer, not an error
    """A gate did not take an approval it was handed, or holds no such authorization."""


@runtime_checkable
class GovernanceGate(Protocol):
    """What a governance system implements to be driven by Agentic-Datacenter."""

    name: str

    def evaluate(
        self, proposal: Proposal, premises: PremiseSnapshot, actor: AuthenticatedActor
    ) -> Decision:
        """Decide on *proposal*, given what the binding established."""
        ...

    def record_outcome(self, decision_ref: str, outcome: Outcome) -> None:
        """Learn what became of a decision."""
        ...


# A gate that authorizes execution itself, instead of leaving it to the control
# path, also has these. They are looked up by name, so a gate without them is
# still a gate:
#
#   enforces_limits: bool
#       True when rate and cumulative limits are the gate's to enforce.
#   approve(decision_ref, approver, now_ms) -> None
#       One person's approval. Raises GateRefusal when it is not taken.
#   reject(decision_ref, approver, reason, now_ms) -> None
#   execute(decision_ref, now_ms, apply, read) -> Outcome
#       Consume the authorization and call ``apply`` at most once to write.
#       ``apply`` returns (status, detail); ``read`` returns a point's value.
#   resolve_unknown(decision_ref, executed, now_ms) -> str
#       Learn what an independent read found for an unanswered write.
