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
    Mandate,
    Outcome,
    PremiseSnapshot,
    Proposal,
    Verdict,
)
from agentic_datacenter.governance.mandates import current as current_authority


def _holds(
    records: dict[str, Mandate], principal: str, contract: str, now_ms: int, depth: int = 8
) -> bool:
    """Whether the last change of *principal* is in force, lists the contract, and may give it."""
    if principal not in records or depth == 0:
        return False
    last = records[principal].changes[-1]
    expired = last.expires_at_ms is not None and now_ms >= last.expires_at_ms
    if contract not in last.contracts or expired:
        return False
    return not last.delegated or _holds(records, last.by, contract, now_ms, depth - 1)


def _ever(records: dict[str, Mandate], principal: str, contract: str, depth: int = 8) -> bool:
    """Whether any change ever gave *principal* the contract."""
    if principal not in records or depth == 0:
        return False
    return any(
        contract in c.contracts and (not c.delegated or _ever(records, c.by, contract, depth - 1))
        for c in records[principal].changes
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
        # Who may act. The premise authority(<principal>, <contract>) says it, and so
        # does the mandate record: every change, oldest first, the last one in force
        # until it expires, if it does. A gate with ``derives_authority = True`` is
        # given the record alone, so this one decides from the record, and reads
        # the premise only when there is none. A gate with
        # ``verifies_mandates = True`` is given signed statements alone, to verify
        # with ``agentic_datacenter.governance.mandates.current``.
        kind, finding = "", None
        if premises.mandate is not None:
            # A change marked ``delegated`` was passed on by ``by``, whose own
            # record is among ``delegators``: it holds only while ``by`` holds
            # the contract too.
            records = {m.principal: m for m in (premises.mandate, *premises.mandate.delegators)}
            who, wanted, now = premises.mandate.principal, proposal.contract_id, premises.time_ms
            if not _holds(records, who, wanted, now):
                kind = "ended" if _ever(records, who, wanted) else "never_held"
            finding = not kind  # optional: this gate's own finding, compared with the premise
        elif premises.statements is not None:
            signed = premises.statements
            found = current_authority(
                signed.statements, signed.issuers, signed.principal, proposal.contract_id,
                premises.time_ms,
            )  # fmt: skip
            kind = "" if found.holds else found.kind or "not_established"
            finding = found.holds
        failed = [p.expr for p in premises.premises if p.holds is False]
        no_authority = bool(kind) or any(e.startswith("authority(") for e in failed)
        verdict, approvers = Verdict.DENY, 0
        if not reasons:
            if any(p.holds is None for p in premises.premises):
                verdict, reasons = Verdict.ABSTAIN, ["a premise cannot be established"]
            elif failed:
                reasons = ["a premise does not hold"]
            elif no_authority:
                reasons = ["the proposer holds no mandate for this contract"]
            elif premises.risk_tier in ("R0", "R1") and premises.approval == "none":
                verdict, reasons = Verdict.ALLOW, ["low risk; premises hold"]
            else:
                # As many people as the contract asks for, never fewer.
                approvers = 2 if premises.approval == "two_person" else 1
                verdict, reasons = Verdict.VERIFY, ["a person must approve"]
        if verdict is Verdict.ALLOW and not premises.writes:
            verdict, reasons = Verdict.DENY, ["nothing that can be executed"]
        # Why, in a word, for every way the step is wrong.
        codes = tuple(
            code
            for code, applies in (
                ("authority", no_authority),
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
            # Optional: which of the two kinds of no mandate the refusal is for.
            authority_detail=kind if "authority" in codes and kind != "not_established" else "",
            authority_holds=finding,
        )  # fmt: skip

    def record_outcome(self, decision_ref: str, outcome: Outcome) -> None:
        """Learn what became of a decision (APPLIED, REJECTED, ROLLED_BACK, UNKNOWN, ...)."""
        self.outcomes[decision_ref] = outcome


def create(contracts: object) -> ExampleGate:
    """Build one gate per run. Agentic-Datacenter calls this once for each run and replay."""
    return ExampleGate()
