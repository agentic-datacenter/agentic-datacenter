"""The REMORA gate binding. The only place in Agentic-Datacenter that imports REMORA.

This binding implements the ``DECISION_ONLY`` operating profile (SDD 9.6, 13):
REMORA decides through ``remora.sdk.evaluate_policy``, a pure function of an
observation, and nothing else of REMORA is used. There is no execution token,
no cumulative-limit enforcement on the REMORA side and no audit chain in this
profile, and its results must never be described as governed execution.

What the binding tells REMORA (the observation) is built only from what the
control path read itself from the supervisory layer. The mapping is documented
in ``docs/design/remora_binding.md``, section 7, and is this project's
interpretation until the REMORA maintainer confirms it.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, distribution
from pathlib import Path

from remora.sdk import GateDecision, GateVerdict, PolicyObservation, evaluate_policy

from agentic_datacenter.governance.envelope_ref import DECISION_TTL_MS, decision_ref
from agentic_datacenter.governance.gate import (
    AuthenticatedActor,
    Decision,
    Outcome,
    PremiseSnapshot,
    Proposal,
    Verdict,
)

#: Agentic-Datacenter risk tier -> REMORA risk tier.
RISK_TIER = {"R0": "low", "R1": "low", "R2": "high"}
_APPROVERS = {"none": 0, "one_operator": 1, "two_person": 2}
_VERDICT = {
    GateVerdict.ALLOW: Verdict.ALLOW,
    GateVerdict.VERIFY: Verdict.VERIFY,
    GateVerdict.ABSTAIN: Verdict.ABSTAIN,
    GateVerdict.DENY: Verdict.DENY,
}
PROFILE = "DECISION_ONLY"


class PinMismatchError(RuntimeError):
    """The installed REMORA is not the commit recorded in REMORA_PIN."""


def pinned_commit(pin_file: Path) -> str:
    """Return the commit recorded in a ``REMORA_PIN`` file."""
    match = re.search(r"^commit:\s*([0-9a-f]{40})\s*$", pin_file.read_text("utf-8"), re.M)
    if match is None:
        raise PinMismatchError(f"{pin_file} has no 40-character commit line")
    return match.group(1)


def installed_commit() -> str | None:
    """Return the commit REMORA was installed from, or None when it is not a Git install."""
    try:
        direct = distribution("remora-assurance").read_text("direct_url.json")
    except PackageNotFoundError:
        return None
    info = json.loads(direct or "{}").get("vcs_info", {})
    commit = info.get("commit_id")
    return str(commit) if commit else None


def check_pin(pin_file: Path) -> str:
    """Refuse to go on unless the installed REMORA is the pinned commit (ADC-PIN-003).

    Returns:
        The commit, for the evidence manifest.

    Raises:
        PinMismatchError: If the installed commit differs from the pin.
    """
    pinned, installed = pinned_commit(pin_file), installed_commit()
    if installed != pinned:
        raise PinMismatchError(
            f"installed REMORA is {installed}, REMORA_PIN says {pinned}; "
            "results from different pins are not comparable"
        )
    return pinned


def observe(proposal: Proposal, premises: PremiseSnapshot) -> PolicyObservation:
    """Build the observation REMORA decides on, from what the control path read.

    - Risk tier: R0 and R1 are ``low``, R2 is ``high``.
    - ``schema_valid`` is false when a write is outside the contract's bounds or step.
    - Every premise established and holding: phase ``ordered``, trust 1.0.
    - A premise that does not hold is a contradiction of the evidence.
    - A premise that could not be established (stale, bad quality, too old):
      phase ``disordered`` and no trust, so nothing is accepted on it.
    """
    established = all(p.holds is not None for p in premises.premises)
    failing = sum(1 for p in premises.premises if p.holds is False)
    holding = sum(1 for p in premises.premises if p.holds is True)
    arguments = json.loads(json.dumps(dict(proposal.arguments), sort_keys=True))
    observation: PolicyObservation = PolicyObservation.from_tool_call(
        name=proposal.contract_id,
        arguments=arguments,
        risk_tier=RISK_TIER.get(premises.risk_tier, "critical"),
        domain="operational-technology",
        action_type="write",
        target_environment="simulation",
        trust_score=1.0 if established and not failing else None,
        phase="ordered" if established else "disordered",
        schema_valid=not premises.bound_errors,
        rollback_available=premises.rollback_available,
        evidence_supporters=holding,
        evidence_contradictions=failing,
    )
    return observation


class RemoraGate:
    """REMORA as an Agentic-Datacenter gate, deciding through the pure policy function."""

    name = "remora"
    profile = PROFILE

    def __init__(self) -> None:
        """Create the gate. Call :func:`check_pin` before a run that will be reported."""
        self.outcomes: dict[str, Outcome] = {}

    @staticmethod
    def installed_commit() -> str | None:
        """Return the commit of the REMORA that is installed, for an evidence bundle."""
        return installed_commit()

    def evaluate(
        self, proposal: Proposal, premises: PremiseSnapshot, actor: AuthenticatedActor
    ) -> Decision:
        """Decide on *proposal*.

        A proposal that cannot be formed (unknown contract, a contract that is
        never available, arguments that do not fit) has no approvable path. It
        is refused here with REMORA's own host-side constructor,
        ``GateDecision.deny``, and never reaches the policy function.
        """
        unformable: list[str] = []
        if not premises.contract_known:
            unformable.append("no such contract")
        elif premises.approval == "not_available":
            unformable.append(f"risk tier {premises.risk_tier}: never automated")
        unformable += list(premises.schema_errors)
        if not unformable and not premises.writes:
            unformable.append("nothing that can be executed")
        tool_call_hash = ""
        if unformable:
            remora: GateDecision = GateDecision.deny(unformable, explanation="cannot be formed")
        else:
            observation = observe(proposal, premises)
            tool_call_hash = str(observation.tool_call_hash or "")
            remora = evaluate_policy(observation)

        verdict = _VERDICT[remora.verdict]
        reasons = [f"remora:{reason}" for reason in remora.reasons]
        approvers = 0
        contract_needs = _APPROVERS.get(premises.approval, 0)
        if verdict is Verdict.VERIFY:
            approvers = max(contract_needs, 2 if remora.escalated else 1)
        elif verdict is Verdict.ALLOW and contract_needs:
            # The contract's approval rule stands whatever the policy decision says.
            verdict, approvers = Verdict.VERIFY, contract_needs
            reasons.append(f"contract requires {premises.approval}")
        reasons += [f"contract:{error}" for error in premises.bound_errors]
        reasons += [
            f"premise not established: {p.expr}" for p in premises.premises if p.holds is None
        ]
        failed = [p for p in premises.premises if p.holds is False]
        reasons += [
            f"premise does not hold: {p.expr}" + (f" ({p.invariant})" if p.invariant else "")
            for p in failed
        ]
        allowed = verdict is Verdict.ALLOW
        writes = [[w.tag, w.value] for w in premises.writes]
        ref = decision_ref(
            self.name,
            proposal.proposal_id,
            proposal.contract_id,
            verdict.value,
            [writes, tool_call_hash],
            reasons,
            premises.time_ms,
        )
        detail: Mapping[str, object] = {
            "profile": PROFILE,
            "remora_action": remora.action.value,
            "remora_verdict": remora.verdict.value,
            "escalated": remora.escalated,
            "tool_call_hash": tool_call_hash,
            "explanation": remora.explanation,
            # Rate and cumulative limits are enforced on REMORA's governed path
            # only. They are reported here and not acted on (SDD 13, M1).
            "limits_not_enforced_in_this_profile": list(premises.limit_errors),
        }
        return Decision(
            verdict=verdict,
            decision_ref=ref,
            contract_id=proposal.contract_id,
            bounded_writes=premises.writes if allowed else (),
            expires_at_ms=premises.time_ms + DECISION_TTL_MS,
            single_use_nonce=ref[-12:],
            reasons=tuple(reasons) or ("remora:accept",),
            required_approvers=approvers,
            escalated=remora.escalated,
            detail=detail,  # type: ignore[arg-type]
        )

    def record_outcome(self, decision_ref: str, outcome: Outcome) -> None:
        """Keep the outcome. The decision-only profile has no REMORA audit chain to append to."""
        self.outcomes[decision_ref] = outcome


def create(contracts: object) -> RemoraGate:
    """Build the gate for a benchmark run. The contract library is not used in this profile."""
    return RemoraGate()
