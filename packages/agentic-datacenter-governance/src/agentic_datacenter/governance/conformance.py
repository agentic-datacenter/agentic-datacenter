"""The gate interface suite (ADC-GOV-004): what every gate binding must satisfy.

A gate from outside this repository is checked with the same function before
it is benchmarked. The suite checks the shape of what a gate returns, not
whether its decisions are good; that is what the benchmark is for.
"""

from __future__ import annotations

from collections.abc import Callable

from agentic_datacenter.governance.gate import (
    AuthenticatedActor,
    BoundedWrite,
    GovernanceGate,
    Outcome,
    PremiseResult,
    PremiseSnapshot,
    Proposal,
    Verdict,
)


class GateConformanceError(AssertionError):
    """A gate binding does not satisfy the gate interface."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise GateConformanceError(message)


def check_gate(make: Callable[[], GovernanceGate]) -> None:
    """Run the interface suite on gates built by *make*.

    Raises:
        GateConformanceError: Naming the first property the gate fails.
    """
    actor = AuthenticatedActor("conformance-agent", "test")
    write = BoundedWrite("cooling.chw_plant[CHW].chws_sp_c", 18.5, 18.0)
    cases = {
        "clean": PremiseSnapshot(
            time_ms=1000, contract_known=True, risk_tier="R1", approval="none", writes=(write,),
            premises=(PremiseResult("all(pod.supply_air_c <= 25.0)", True, "holds"),),
            rollback_available=True,
        ),
        "unknown contract": PremiseSnapshot(time_ms=1000, contract_known=False),
        "bad arguments": PremiseSnapshot(
            time_ms=1000, contract_known=True, risk_tier="R1", approval="none",
            schema_errors=("setpoint_c must be a number",),
        ),
        "stale premise": PremiseSnapshot(
            time_ms=1000, contract_known=True, risk_tier="R1", approval="none", writes=(write,),
            premises=(PremiseResult("tes.charge_pct >= 80", None, "stale"),),
        ),
    }  # fmt: skip
    gate = make()
    _require(isinstance(gate, GovernanceGate), "does not implement GovernanceGate")
    _require(bool(getattr(gate, "name", "")), "has no name")
    seen = set()
    for label, snapshot in cases.items():
        proposal = Proposal(f"prop-{label}", "chw.set_supply_setpoint.v1", {"setpoint_c": 18.5})
        decision = gate.evaluate(proposal, snapshot, actor)
        again = make().evaluate(proposal, snapshot, actor)
        _require(isinstance(decision.verdict, Verdict), f"{label}: verdict is not a Verdict")
        _require(bool(decision.decision_ref), f"{label}: no decision reference")
        _require(decision.decision_ref not in seen, f"{label}: decision reference reused")
        seen.add(decision.decision_ref)
        _require(decision.contract_id == proposal.contract_id, f"{label}: wrong contract id")
        _require(bool(decision.reasons), f"{label}: no reasons given")
        _require(
            (decision.verdict, decision.decision_ref, decision.bounded_writes, decision.reasons)
            == (again.verdict, again.decision_ref, again.bounded_writes, again.reasons),
            f"{label}: the same input gave a different decision",
        )
        if decision.verdict is Verdict.ALLOW:
            _require(bool(decision.bounded_writes), f"{label}: ALLOW without writes")
            _require(
                set(decision.bounded_writes) <= set(snapshot.writes),
                f"{label}: ALLOW names a write the contract instance does not make",
            )
            _require(decision.expires_at_ms > snapshot.time_ms, f"{label}: ALLOW does not expire")
            _require(bool(decision.single_use_nonce), f"{label}: ALLOW without a nonce")
        else:
            _require(not decision.bounded_writes, f"{label}: writes on a verdict that is not ALLOW")
        if decision.verdict is Verdict.VERIFY:
            _require(decision.required_approvers >= 1, f"{label}: VERIFY needs an approver count")
        gate.record_outcome(decision.decision_ref, Outcome("NOT_EXECUTED", "conformance"))
    for label in ("unknown contract", "bad arguments"):
        proposal = Proposal(f"prop-{label}", "chw.set_supply_setpoint.v1", {})
        verdict = make().evaluate(proposal, cases[label], actor).verdict
        _require(verdict is not Verdict.ALLOW, f"{label}: allowed something that cannot be formed")
