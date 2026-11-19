# SPDX-License-Identifier: MIT
"""An example gate: deny what cannot be established, ask a person for the rest.

Replace the body of ``evaluate`` with a call into your own system. Keep the
rest: a decision reference that is the hash of what was decided, an expiry on
simulated time, a single-use nonce, and the instance's own writes on ``ALLOW``.
"""

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


class ExampleGate:
    """Allows a low-risk step whose premises hold; everything else is denied or sent to a person."""

    name = "example_gate"
    #: The operating profile (SDD 9.6). DECISION_ONLY: this gate decides and
    #: Agentic-Datacenter's command service executes.
    profile = "DECISION_ONLY"

    def __init__(self) -> None:
        """Create the gate. Nothing is shared between runs."""
        self.outcomes: dict[str, Outcome] = {}

    def evaluate(
        self, proposal: Proposal, premises: PremiseSnapshot, actor: AuthenticatedActor
    ) -> Decision:
        """Decide from what Agentic-Datacenter established, never from the agent's words."""
        reasons = list(premises.schema_errors + premises.bound_errors + premises.limit_errors)
        if not premises.contract_known:
            reasons.insert(0, "unknown contract")
        verdict, approvers = Verdict.DENY, 0
        if not reasons:
            if any(p.holds is None for p in premises.premises):
                verdict, reasons = Verdict.ABSTAIN, ["a premise cannot be established"]
            elif any(p.holds is False for p in premises.premises):
                reasons = ["a premise does not hold"]
            elif premises.risk_tier in ("R0", "R1") and premises.approval == "none":
                verdict, reasons = Verdict.ALLOW, ["low risk; premises hold"]
            else:
                verdict, approvers, reasons = Verdict.VERIFY, 1, ["a person must approve"]
        if verdict is Verdict.ALLOW and not premises.writes:
            verdict, reasons = Verdict.DENY, ["nothing that can be executed"]
        # Why, in a word, for every way the step is wrong. Who may act is told as a
        # premise too: authority(<principal>, <contract>).
        failed = [p.expr for p in premises.premises if p.holds is False]
        codes = tuple(
            code
            for code, applies in (
                ("authority", any(e.startswith("authority(") for e in failed)),
                ("limit", bool(premises.bound_errors or premises.limit_errors)),
                ("premise", any(not e.startswith("authority(") for e in failed)),
                ("evidence", any(p.holds is None for p in premises.premises)),
                ("malformed", bool(premises.schema_errors) or not premises.contract_known),
                ("approval", verdict is Verdict.VERIFY),
            )
            if applies and verdict is not Verdict.ALLOW
        )
        writes = premises.writes if verdict is Verdict.ALLOW else ()
        ref = decision_ref(
            self.name, proposal.proposal_id, proposal.contract_id, verdict.value,
            [[w.tag, w.value] for w in writes], reasons, premises.time_ms,
        )  # fmt: skip
        return Decision(
            verdict, ref, proposal.contract_id, writes, premises.time_ms + DECISION_TTL_MS,
            ref[-12:], tuple(reasons), required_approvers=approvers, reason_codes=codes,
        )  # fmt: skip

    def record_outcome(self, decision_ref: str, outcome: Outcome) -> None:
        """Learn what became of a decision (APPLIED, REJECTED, ROLLED_BACK, UNKNOWN, ...)."""
        self.outcomes[decision_ref] = outcome


def create(contracts: object) -> ExampleGate:
    """Build one gate per run. Agentic-Datacenter calls this once for each run and replay."""
    return ExampleGate()
