"""The ungoverned baseline: everything that can be executed is allowed."""

from __future__ import annotations

from agentic_datacenter.governance.envelope_ref import DECISION_TTL_MS, decision_ref
from agentic_datacenter.governance.gate import (
    AuthenticatedActor,
    Decision,
    Outcome,
    PremiseSnapshot,
    Proposal,
    Verdict,
)


class NullGate:
    """Allows every proposal whose writes can be formed. It looks at nothing else.

    This is the ``UNGOVERNED`` operating profile: it shows what an agent does to
    the plant when nothing stands between its proposals and the command service.
    Tier, range and rate checks in the command service still apply.
    """

    name = "null_gate"
    profile = "UNGOVERNED"

    def __init__(self) -> None:
        """Create the gate."""
        self.outcomes: dict[str, Outcome] = {}

    def evaluate(
        self, proposal: Proposal, premises: PremiseSnapshot, actor: AuthenticatedActor
    ) -> Decision:
        """Allow whenever there is something to execute."""
        allow = bool(premises.writes) and not premises.schema_errors
        verdict = Verdict.ALLOW if allow else Verdict.DENY
        reasons = ("no gate",) if allow else ("nothing that can be executed",)
        writes = [[w.tag, w.value] for w in premises.writes]
        ref = decision_ref(
            self.name,
            proposal.proposal_id,
            proposal.contract_id,
            verdict.value,
            writes,
            list(reasons),
            premises.time_ms,
        )
        return Decision(
            verdict,
            ref,
            proposal.contract_id,
            premises.writes if allow else (),
            premises.time_ms + DECISION_TTL_MS,
            ref[-12:],
            reasons,
        )

    def record_outcome(self, decision_ref: str, outcome: Outcome) -> None:
        """Keep the outcome."""
        self.outcomes[decision_ref] = outcome


def create(contracts: object) -> NullGate:
    """Build the gate for a benchmark run. The contract library is not used."""
    return NullGate()
