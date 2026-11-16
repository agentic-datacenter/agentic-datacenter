"""The conventional baseline: a role allowlist and range checks, nothing else."""

from __future__ import annotations

from collections.abc import Iterable

from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.envelope_ref import DECISION_TTL_MS, decision_ref
from agentic_datacenter.governance.gate import (
    AuthenticatedActor,
    Decision,
    Outcome,
    PremiseSnapshot,
    Proposal,
    Verdict,
)


class StaticAllowlist:
    """Allows a listed contract whose values are inside its range.

    It stands for a conventional building management permission model: this
    principal may change these setpoints between these limits. It does not look
    at plant state, step size, rate or accumulated change, and it has no notion
    of human approval: a contract is on the list or it is not.
    """

    name = "static_allowlist"
    profile = "STATIC_ALLOWLIST"

    def __init__(self, allowed: Iterable[str]) -> None:
        """Create the gate with the contract ids the agent role may use."""
        self.allowed = frozenset(allowed)
        self.outcomes: dict[str, Outcome] = {}

    def evaluate(
        self, proposal: Proposal, premises: PremiseSnapshot, actor: AuthenticatedActor
    ) -> Decision:
        """Allow a listed contract with in-range values; deny everything else."""
        reasons: list[str] = []
        if proposal.contract_id not in self.allowed or not premises.contract_known:
            reasons.append("contract is not on the allowlist")
        reasons += list(premises.schema_errors)
        reasons += [e for e in premises.bound_errors if e.startswith("range:")]
        if not premises.writes and not reasons:
            reasons.append("nothing that can be executed")
        verdict = Verdict.DENY if reasons else Verdict.ALLOW
        shown = tuple(reasons) or ("on the allowlist and inside its range",)
        writes = [[w.tag, w.value] for w in premises.writes]
        ref = decision_ref(
            self.name,
            proposal.proposal_id,
            proposal.contract_id,
            verdict.value,
            writes,
            list(shown),
            premises.time_ms,
        )
        return Decision(
            verdict,
            ref,
            proposal.contract_id,
            () if reasons else premises.writes,
            premises.time_ms + DECISION_TTL_MS,
            ref[-12:],
            shown,
        )

    def record_outcome(self, decision_ref: str, outcome: Outcome) -> None:
        """Keep the outcome."""
        self.outcomes[decision_ref] = outcome


def create(contracts: ContractLibrary) -> StaticAllowlist:
    """Build the gate for a benchmark run: the agent role may use every R1 contract."""
    allowed = []
    for contract_id in contracts.ids():
        contract = contracts.get(contract_id)
        if contract is not None and contract.risk_tier == "R1":
            allowed.append(contract_id)
    return StaticAllowlist(allowed)
