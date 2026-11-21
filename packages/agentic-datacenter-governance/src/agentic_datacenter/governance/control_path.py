"""The control path from proposal to write (SDD 9.1).

1. The agent proposes a contract instance. It never names a raw tag write.
2. The binding reads the contract's premises itself from the supervisory layer.
3. The gate decides: allow, deny, verify (a human must approve) or abstain.
4. For allow, or verify after approval, the writes go to the Supervisory
   Command Service, each with a single-use decision reference. The service
   checks tier, range and rate again.
5. The outcome is recorded with the decision and given back to the gate.

What happens after the decision depends on the operating profile (SDD 9.6).
"""

from __future__ import annotations

import copy
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace

from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary, fill
from agentic_datacenter.governance.envelope_ref import DECISION_TTL_MS, write_ref
from agentic_datacenter.governance.gate import (
    AUTHORITY_DETAILS,
    REASON_CODES,
    AuthenticatedActor,
    BoundedWrite,
    Decision,
    GateRefusal,
    GovernanceGate,
    Mandate,
    MandateChange,
    Outcome,
    PremiseResult,
    Proposal,
    Verdict,
)
from agentic_datacenter.governance.premises import (
    AppliedWrite,
    PremiseReader,
    build_snapshot,
    check_expr,
    split_hold,
)
from agentic_datacenter.supervisory.command_service import Actor, CommandService
from agentic_datacenter.supervisory.overview import Overview
from agentic_datacenter.supervisory.points import PointDatabase

#: Operating profile -> whether an allowed proposal is executed (SDD 9.6).
PROFILES = {
    "BASELINE_RULES": False,
    "UNGOVERNED": True,
    "STATIC_ALLOWLIST": True,
    "SHADOW": False,
    "GOVERNED": True,
    "DECISION_ONLY": True,
}
#: Profiles in which a contract's rollback is watched. Without a gate, and with
#: an allowlist that only checks ranges, nothing enforces the rest of a contract.
ROLLBACK_PROFILES = frozenset({"GOVERNED", "DECISION_ONLY", "SHADOW"})
#: What the record says when an approval came from someone without standing.
NO_STANDING = "holds no standing to approve this contract"
_ROLLBACK_ACTOR = Actor("rollback-monitor", "operator")
#: How long an unanswered write is left before the plant is read to see what became of it.
UNKNOWN_RESOLVE_MS = 30_000
#: How long a premise of an applied step may stay unestablished before the step is undone.
PREMISE_LOSS_HOLD_S = 10
#: The outcome detail of a proposal a person has not answered yet, and how the
#: detail of one a person rejected begins. Both say that a person was asked.
WAITING_FOR_APPROVAL = "waiting for approval"
REJECTED_BY = "rejected by "
_UNGATED = NullGate()


@dataclass
class _Watch:
    """An applied proposal whose rollback trigger and premises are being watched.

    *writes* holds, per point, the value to go back to: the value before the
    first of the agent's writes that are still standing on that point, not
    merely the one before the latest step. *premises* are the premises the
    step was allowed on, filled in, with their freshness limits.
    """

    proposal_id: str
    trigger: str
    since_ms: int
    writes: list[tuple[str, bool | int | float | str]]
    premises: list[tuple[str, float]] = field(default_factory=list)
    lost_since_ms: int = -1
    #: Why the step is being undone, once that is decided. The undo is then
    #: tried every second until every write is accepted.
    undo: str = ""
    #: The agent's steps still standing on these points, oldest first: the
    #: proposals an undo takes back. A step back toward safety is not one of them.
    chain: list[str] = field(default_factory=list)


class GovernedPath:
    """Runs proposals through a gate and, where the profile says so, to the plant."""

    def __init__(
        self,
        kernel: Kernel,
        points: PointDatabase,
        service: CommandService,
        library: ContractLibrary,
        gate: GovernanceGate,
        profile: str,
        key_sets: Mapping[str, tuple[str, ...]],
    ) -> None:
        """Create the path for one gate under one operating profile.

        Raises:
            ValueError: If the profile is unknown.
            ContractError: If the library does not fit the facility or uses an
                unsupported premise.
        """
        if profile not in PROFILES:
            raise ValueError(f"unknown operating profile {profile!r}")
        self._kernel, self._points, self._service = kernel, points, service
        self.library, self.gate, self.profile = library, gate, profile
        self._key_sets = {name: tuple(keys) for name, keys in key_sets.items()}
        self.notes: list[str] = []
        self._reader = PremiseReader(points, Overview(points, self.notes))
        library.check_against(points, self._key_sets)
        for contract_id in library.ids():
            contract = library.get(contract_id)
            assert contract is not None
            for premise in contract.premises:
                check_expr(premise.expr)
            if contract.rollback:
                check_expr(contract.rollback.trigger)
        #: Proposal ids whose decision is replaced in a counterfactual replay:
        #: ``execute`` (as if no gate stood in the way) or ``block``.
        self.forced: dict[str, str] = {}
        #: Every change to each principal's mandate, oldest first; the last is in
        #: force. None until a mandate is first set: then nothing is said about
        #: authority, and every principal may propose every contract, as before
        #: authority was modelled.
        self._authority: dict[str, list[MandateChange]] | None = None
        self._records: list[dict[str, JsonValue]] = []
        self._history: list[AppliedWrite] = []
        self._watches: list[_Watch] = []
        #: Unanswered writes: proposal id, when, and what was meant to be written.
        self._unknown: list[tuple[str, int, list[BoundedWrite]]] = []
        self._gate_limits = bool(getattr(gate, "enforces_limits", False))
        #: A gate that works out for itself who may act is not told the answer.
        self._derives_authority = bool(getattr(gate, "derives_authority", False))
        #: How far ahead the agent's own clock runs (scenario AD-09). Reported, never used.
        self.agent_clock_skew_ms = 0
        kernel.state.register("governance.path", self, tracked=True)
        kernel.add_task("governance.rollback", self._watch_rollbacks, period_ms=1000)
        kernel.add_task("governance.unknown", self._resolve_unknowns, period_ms=1000)

    def now_ms(self) -> int:
        """Return the time on this path's clock."""
        return self._kernel.clock.now_ms

    def add_note(self, text: str) -> None:
        """Add free text that is shown with the alarms: a work order, an operator comment."""
        self.notes.append(text)
        self._kernel.state.touch("governance.path")

    # -- authority -----------------------------------------------------------------

    def set_authority(
        self, principal: str, contracts: Sequence[str] | None, by: str = "", reason: str = ""
    ) -> None:
        """Set the mandate of *principal*: the contracts it may propose from now on.

        None is every contract of the library; an empty sequence ends the
        mandate. A principal a mandate was set for holds it only for what was
        set, and every proposal it makes carries the premise
        ``authority(<principal>, <contract>)`` beside the contract's own. It is
        established here, from this register, never from what the agent says.
        For a person, the mandate is what that person may approve: an approval
        from someone without it is not taken. A principal no mandate was ever
        set for is not restricted.

        The register keeps every change, with the time, *by* (who made it) and
        *reason*, and gives them to the gate with each proposal (:meth:`mandate`).

        Raises:
            ValueError: If a contract is not in the library.
        """
        known = set(self.library.ids())
        wanted = known if contracts is None else set(contracts)
        if not wanted <= known:
            raise ValueError(f"no such contract: {', '.join(sorted(wanted - known))}")
        if self._authority is None:
            self._authority = {}
        change = MandateChange(self._kernel.clock.now_ms, tuple(sorted(wanted)), by, reason)
        self._authority.setdefault(principal, []).append(change)
        self._kernel.state.touch("governance.path")

    def authorized(self, principal: str, contract_id: str) -> bool | None:
        """Whether *principal* holds a mandate for *contract_id*; None if none was set for it."""
        if self._authority is None or principal not in self._authority:
            return None
        return contract_id in self._authority[principal][-1].contracts

    def mandate(self, principal: str) -> Mandate | None:
        """Return the record of *principal*'s mandate; None if none was ever set for it."""
        if self._authority is None or principal not in self._authority:
            return None
        return Mandate(principal, tuple(self._authority[principal]))

    def _no_mandate(self, principal: str, contract_id: str) -> str:
        """Say which kind of no mandate it is, from the register: one of ``AUTHORITY_DETAILS``.

        ``ended`` when an earlier change held the contract, ``never_held``
        otherwise. The time before the first change is not a mandate: nothing
        was said about authority then.
        """
        assert self._authority is not None
        earlier = self._authority[principal][:-1]
        return "ended" if any(contract_id in c.contracts for c in earlier) else "never_held"

    # -- proposing -----------------------------------------------------------------

    def propose(
        self,
        actor: AuthenticatedActor,
        contract_id: str,
        arguments: Mapping[str, JsonValue],
        rationale: str = "",
        claimed_actor: str | None = None,
        claimed_time_ms: int | None = None,
    ) -> dict[str, JsonValue]:
        """Submit one contract instance and return its record.

        *claimed_time_ms* is what the agent says the time is. It is stored as a
        claim; every decision and every expiry is on this path's own clock.
        """
        now = self._kernel.clock.now_ms
        proposal = Proposal(
            f"prop-{len(self._records):05d}", contract_id, dict(arguments), rationale, claimed_actor
        )
        record: dict[str, JsonValue] = {
            "proposal_id": proposal.proposal_id, "time_ms": now, "profile": self.profile,
            "gate": self.gate.name, "principal": actor.principal, "credential": actor.credential,
            "claimed_actor": claimed_actor, "claimed_time_ms": claimed_time_ms,
            "contract_id": contract_id,
            "arguments": dict(arguments), "rationale": rationale,
            "verdict": None, "decision_ref": None, "reasons": [], "writes": [],
            "premises": [], "limit_errors": [], "required_approvers": 0, "approvers": [],
            "escalated": False, "approval_refusals": [], "was_unknown": False,
            "gate_overreach": False, "contract_errors": [],
            "outcome": "NOT_EXECUTED", "outcome_detail": "",
        }  # fmt: skip
        self._records.append(record)
        self._kernel.state.touch("governance.path")
        if self.profile == "BASELINE_RULES":
            record["outcome_detail"] = "this profile takes no proposals"
            return copy.deepcopy(record)
        snapshot = build_snapshot(
            self.library.get(contract_id),
            arguments,
            self._reader,
            self._points,
            self._key_sets,
            self._history,
            now,
            self.restore_origins(),
        )
        authorized = self.authorized(actor.principal, contract_id)
        shown = snapshot
        if authorized is not None:
            # Told to the gate as a premise, the form in which every gate is
            # already told what was established about a proposal.
            held = "holds a mandate" if authorized else "holds no mandate"
            premise = PremiseResult(
                f"authority({actor.principal}, {contract_id})",
                authorized,
                f"{actor.principal} {held} for this contract",
            )
            # The record the premise was established from goes to every gate, for
            # one that works out for itself who may act (ADR 0031).
            shown = replace(snapshot, mandate=self.mandate(actor.principal))
            snapshot = replace(shown, premises=(*snapshot.premises, premise))
            if not self._derives_authority:
                shown = snapshot
            else:
                # Such a gate is given the record and not the answer. The record
                # of the proposal keeps the premise: the run is judged by it.
                record["authority_premise_told"] = False
            record["authorized"] = authorized
            if not authorized:
                record["authority_detail"] = self._no_mandate(actor.principal, contract_id)
        decision = self.gate.evaluate(proposal, shown, actor)
        # Whatever a gate returns, an ALLOW authorizes at most the writes of this
        # contract instance, as built here (INV-GOV-2). A gate from another
        # project is not trusted to keep to that; one that names other writes is
        # refused, and the attempt is counted against it.
        overreach = decision.verdict is Verdict.ALLOW and not set(decision.bounded_writes) <= set(
            snapshot.writes
        )
        if overreach:
            decision = Decision(
                Verdict.DENY,
                decision.decision_ref,
                proposal.contract_id,
                reasons=(
                    "control path: the gate authorized writes this contract instance does not make",
                    *decision.reasons,
                ),
            )
        record["gate_overreach"] = overreach
        forced = self.forced.get(proposal.proposal_id)
        if forced == "execute":
            decision = _UNGATED.evaluate(proposal, snapshot, actor)
        elif forced == "block":
            decision = Decision(
                Verdict.DENY,
                decision.decision_ref + "-blocked",
                proposal.contract_id,
                reasons=("counterfactual: not executed",),
            )
        if decision.reason_codes:
            # Only when the gate gave any, so a gate that gives none has the
            # records, and the state hashes, it had before. In the list's order,
            # each once.
            given = [c if c in REASON_CODES else "other" for c in decision.reason_codes]
            record["reason_codes"] = [c for c in REASON_CODES if c in given]
        if decision.authority_holds is not None and authorized is not None:
            # The gate's own finding, kept beside the premise it is compared with.
            # Only where a mandate was set: elsewhere there is nothing to compare.
            record["gate_authority_holds"] = bool(decision.authority_holds)
        if decision.authority_detail and decision.verdict is not Verdict.ALLOW:
            # Which kind of no mandate the gate refused for, if it said. A word of
            # its own is kept as ``other``, as with the codes.
            said = decision.authority_detail
            record["reason_details"] = {"authority": said if said in AUTHORITY_DETAILS else "other"}
        record.update({
            "verdict": decision.verdict.value, "decision_ref": decision.decision_ref,
            "reasons": list(decision.reasons), "escalated": decision.escalated,
            "writes": [[w.tag, w.value, w.previous] for w in decision.bounded_writes],
            "premises": [asdict(p) for p in snapshot.premises],
            "limit_errors": list(snapshot.limit_errors),
            "contract_errors": [*snapshot.schema_errors, *snapshot.bound_errors],
            "required_approvers": decision.required_approvers,
            "expires_at_ms": decision.expires_at_ms,
        })  # fmt: skip
        self._kernel.events.publish("governance.decision", {
            "proposal_id": proposal.proposal_id, "verdict": decision.verdict.value,
            "contract_id": contract_id, "decision_ref": decision.decision_ref,
        })  # fmt: skip
        if decision.verdict is Verdict.ALLOW:
            if PROFILES[self.profile] or forced == "execute":
                self._execute(
                    record, decision.bounded_writes, decision.decision_ref, forced == "execute"
                )
            else:
                self._finish(record, "NOT_EXECUTED", "shadow: decisions are recorded only")
        elif decision.verdict is Verdict.VERIFY:
            record["outcome_detail"] = WAITING_FOR_APPROVAL
        else:
            self._finish(record, "NOT_EXECUTED", decision.verdict.value.lower())
        return copy.deepcopy(record)

    # -- approval ---------------------------------------------------------------------

    def approve(self, proposal_id: str, approver: str) -> dict[str, JsonValue]:
        """Record one human approval; execute when enough distinct people have approved.

        The premises are read again at that moment. If one no longer holds, the
        proposal is not executed: an approval is for the plant as it was shown.
        """
        record = self._pending(proposal_id)
        approvers = record["approvers"]
        assert isinstance(approvers, list)
        if approver == record["principal"]:
            raise ValueError("the proposer cannot approve its own proposal")
        now = self._kernel.clock.now_ms
        self._kernel.state.touch("governance.path")
        if approver not in approvers:
            if self.authorized(approver, str(record["contract_id"])) is False:
                # Someone who has lost access. It is refused here, before any
                # gate is asked: who may approve is not a gate's to decide.
                refused = record["approval_refusals"]
                assert isinstance(refused, list)
                refused.append(f"{approver}: {NO_STANDING}")
                return copy.deepcopy(record)
            hook = getattr(self.gate, "approve", None)
            if hook is not None:
                try:
                    hook(str(record["decision_ref"]), approver, now)
                except GateRefusal as exc:
                    refused = record["approval_refusals"]
                    assert isinstance(refused, list)
                    refused.append(f"{approver}: {exc}")
                    return copy.deepcopy(record)
            approvers.append(approver)
        if len(approvers) < int(str(record["required_approvers"])):
            return copy.deepcopy(record)
        if not PROFILES[self.profile]:
            self._finish(record, "NOT_EXECUTED", "shadow: decisions are recorded only")
            return copy.deepcopy(record)
        arguments = record["arguments"]
        assert isinstance(arguments, dict)
        snapshot = build_snapshot(
            self.library.get(str(record["contract_id"])),
            arguments,
            self._reader,
            self._points,
            self._key_sets,
            self._history,
            now,
            self.restore_origins(),
        )
        failed = [p.expr for p in snapshot.premises if p.holds is not True]
        proposer, contract_id = str(record["principal"]), str(record["contract_id"])
        if self.authorized(proposer, contract_id) is False:
            # Asked for while the proposer held a mandate, answered after it ended.
            failed.append(f"authority({proposer}, {contract_id})")
        problems = [*snapshot.schema_errors, *snapshot.bound_errors]
        if not self._gate_limits:
            problems += snapshot.limit_errors
        if failed or problems:
            detail = "; ".join(
                [*problems, *(f"premise no longer established: {f}" for f in failed)]
            )
            self._finish(record, "REJECTED", detail)
        else:
            self._execute(record, snapshot.writes, f"{record['decision_ref']}+approved")
        return copy.deepcopy(record)

    def reject(self, proposal_id: str, approver: str, reason: str) -> dict[str, JsonValue]:
        """Refuse a proposal that is waiting for approval."""
        record = self._pending(proposal_id)
        hook = getattr(self.gate, "reject", None)
        if hook is not None:
            try:
                hook(str(record["decision_ref"]), approver, reason, self._kernel.clock.now_ms)
            except GateRefusal as exc:
                reason = f"{reason} (gate: {exc})"
        self._finish(record, "REJECTED", f"{REJECTED_BY}{approver}: {reason}")
        return copy.deepcopy(record)

    def _pending(self, proposal_id: str) -> dict[str, JsonValue]:
        for record in self._records:
            if record["proposal_id"] == proposal_id:
                waiting = (
                    record["verdict"] == "VERIFY"
                    and record["outcome_detail"] == WAITING_FOR_APPROVAL
                )
                if not waiting:
                    raise ValueError(f"{proposal_id} is not waiting for approval")
                return record
        raise KeyError(proposal_id)

    # -- execution ---------------------------------------------------------------------

    def _execute(
        self,
        record: dict[str, JsonValue],
        writes: tuple[BoundedWrite, ...],
        reference: str,
        ungated: bool = False,
    ) -> None:
        """Write what was authorized, through the gate when the gate releases execution.

        *ungated* is the counterfactual "as if no gate stood in the way": the
        gate is not asked to release anything.
        """
        now = self._kernel.clock.now_ms
        done: list[BoundedWrite] = []
        release = None if ungated else getattr(self.gate, "execute", None)
        if release is None or record["decision_ref"] is None:
            status, detail = self._apply(record, writes, reference, done)
        else:
            outcome = release(
                str(record["decision_ref"]),
                now,
                lambda: self._apply(record, writes, reference, done),
                lambda tag: self._points.read(tag).value,
            )
            status, detail = outcome.status, outcome.detail
        if status == "APPLIED":
            self._applied(record, done)
        elif status == "UNKNOWN":
            # The grant is spent and nobody knows whether the write landed. It is
            # not tried again; the plant is read later to find out (ADC-GOV-007).
            record["was_unknown"] = True
            self._unknown.append((str(record["proposal_id"]), now, list(writes)))
        self._finish(record, status, detail)

    def _apply(
        self,
        record: dict[str, JsonValue],
        writes: tuple[BoundedWrite, ...],
        reference: str,
        done: list[BoundedWrite],
    ) -> tuple[str, str]:
        """Send each write to the command service once. Return the status and why."""
        now = self._kernel.clock.now_ms
        agent = Actor(str(record["principal"]), "agent")
        reason = f"{record['contract_id']} ({record['proposal_id']})"
        for index, write in enumerate(writes):
            ref = write_ref(reference, index)
            self._service.authorize(ref, write.tag, write.value, now + DECISION_TTL_MS)
            result = self._service.write(write.tag, write.value, agent, reason, decision_ref=ref)
            if result.code == "TIMEOUT":
                return "UNKNOWN", f"{write.tag}: no answer from the command service"
            if not result.accepted:
                for earlier in reversed(done):
                    self._service.write(
                        earlier.tag,
                        earlier.previous,
                        _ROLLBACK_ACTOR,
                        f"undo partial {record['proposal_id']}",
                    )
                done.clear()
                return "REJECTED", f"{write.tag}: {result.code}"
            done.append(write)
        return "APPLIED", ""

    def _applied(self, record: dict[str, JsonValue], done: list[BoundedWrite]) -> None:
        """Count applied writes against the limits and start watching the rollback trigger."""
        now = self._kernel.clock.now_ms
        for write in done:
            numeric = isinstance(write.value, float) and isinstance(write.previous, int | float)
            delta = float(write.value) - float(write.previous) if numeric else 0.0
            self._history.append(AppliedWrite(now, str(record["contract_id"]), write.tag, delta))
        contract = self.library.get(str(record["contract_id"]))
        watched = self.profile in ROLLBACK_PROFILES
        if watched and contract is not None and contract.rollback is not None:
            arguments = record["arguments"]
            assert isinstance(arguments, dict)
            text = {name: str(value) for name, value in arguments.items()}
            tags = {w.tag for w in done}
            # A newer write to a tag replaces the watch on the older one, and
            # inherits how far back the older one would have gone (INV-GOV-7).
            origins = self.restore_origins()
            replaced = [w for w in self._watches if tags & {t for t, _ in w.writes}]
            self._watches = [w for w in self._watches if all(w is not r for r in replaced)]
            restore = [(w.tag, origins.get(w.tag, w.previous)) for w in done]
            if all(_same(value, w.value) for (_, value), w in zip(restore, done, strict=True)):
                return  # back where the agent started: nothing left to undo
            directions = set()
            for write in done:
                if isinstance(write.value, float) and isinstance(write.previous, int | float):
                    if write.value > float(write.previous):
                        directions.add("increase")
                    elif write.value < float(write.previous):
                        directions.add("decrease")
            # A step only in the safe direction leaves part of an earlier step
            # standing. What is left is watched on that step's premises; the
            # undo goes to the origin, so it never moves the plant up again.
            inherited = [i for w in replaced for i in (w.chain or [w.proposal_id])]
            chain = list(dict.fromkeys(inherited))
            if directions == {contract.safe_direction()}:
                premises = [p for w in replaced for p in w.premises]
            else:
                chain.append(str(record["proposal_id"]))
                premises = [
                    (fill(p.expr, text), p.max_age_s)
                    for p in contract.premises
                    if p.when == "always" or p.when in directions
                ]
            trigger = fill(contract.rollback.trigger, text)
            self._watches.append(
                _Watch(str(record["proposal_id"]), trigger, -1, restore, premises, chain=chain)
            )

    def restore_origins(self) -> dict[str, float]:
        """Return, per point under watch, the numeric value it had before the agent moved it."""
        out: dict[str, float] = {}
        for watch in self._watches:
            for tag, value in watch.writes:
                if isinstance(value, int | float) and not isinstance(value, bool):
                    out[tag] = float(value)
        return out

    def _resolve_unknowns(self) -> None:
        """Find out what became of an unanswered write, from the plant and nothing else."""
        if not self._unknown:
            return
        now = self._kernel.clock.now_ms
        keep = []
        for proposal_id, since, writes in self._unknown:
            if now - since < UNKNOWN_RESOLVE_MS:
                keep.append((proposal_id, since, writes))
                continue
            in_place = [w for w in writes if self._points.read(w.tag).value == w.value]
            landed = len(in_place) == len(writes)
            for record in self._records:
                if record["proposal_id"] != proposal_id:
                    continue
                told = ""
                hook = getattr(self.gate, "resolve_unknown", None)
                if hook is not None and record["decision_ref"] is not None:
                    # The gate is told about the first write, the one it meters.
                    first = bool(in_place) and in_place[0] == writes[0]
                    told = f"; gate: {hook(str(record['decision_ref']), first, now)}"
                if landed:
                    self._applied(record, in_place)
                    status, found = "APPLIED", "the write is in place"
                elif not in_place:
                    status, found = "REJECTED", "the write is not in place"
                else:
                    # Half a contract instance is not a state to leave the plant in.
                    for write in reversed(in_place):
                        self._service.write(
                            write.tag, write.previous, _ROLLBACK_ACTOR,
                            f"restore after partly applied {proposal_id}",
                        )  # fmt: skip
                    status = "ROLLED_BACK"
                    found = f"{len(in_place)} of {len(writes)} writes in place; restored"
                self._finish(
                    record, status, f"was unknown; an independent read found {found}{told}"
                )
        self._unknown = keep
        self._kernel.state.touch("governance.path")

    def _finish(self, record: dict[str, JsonValue], status: str, detail: str) -> None:
        record["outcome"], record["outcome_detail"] = status, detail
        self._kernel.state.touch("governance.path")
        if record["decision_ref"] is not None:
            self.gate.record_outcome(str(record["decision_ref"]), Outcome(status, detail))
        self._kernel.events.publish("governance.outcome", {
            "proposal_id": record["proposal_id"], "outcome": status, "detail": detail,
        })  # fmt: skip

    # -- rollback ----------------------------------------------------------------------

    def _watch_rollbacks(self) -> None:
        """Undo an applied step whose trigger fires or whose premises are lost.

        Both checks fail safe. A trigger that cannot be read counts as fired
        (INV-GOV-3 applied to undoing), and a premise the step was allowed on
        that no longer holds, or can no longer be established, for
        ``PREMISE_LOSS_HOLD_S`` undoes it (INV-GOV-7). The undo goes back to
        the value before the agent's first standing write on each point and is
        made by the rollback monitor, so no limit of the agent's holds it back.
        """
        if not self._watches:
            return
        now = self._kernel.clock.now_ms
        keep = []
        for watch in self._watches:
            if not watch.undo:
                watch.undo = self._fired(watch, now) or self._premise_lost(watch, now)
                if not watch.undo:
                    keep.append(watch)
                    continue
                self._kernel.state.touch("governance.path")
            refused = []
            for tag, previous in watch.writes:
                result = self._service.write(
                    tag, previous, _ROLLBACK_ACTOR, f"rollback of {watch.proposal_id}: {watch.undo}"
                )
                if not result.accepted:
                    refused.append(f"{tag}: {result.code}")
            if refused:
                # Not undone until the plant has every value back: try again.
                keep.append(watch)
                continue
            undone = set(watch.chain or [watch.proposal_id])
            for record in self._records:
                if record["proposal_id"] in undone and record["outcome"] == "APPLIED":
                    self._finish(record, "ROLLED_BACK", watch.undo)
        self._watches = keep

    def _fired(self, watch: _Watch, now: int) -> str:
        condition, hold_s = split_hold(watch.trigger)
        holds = self._reader.evaluate(condition, 3600.0, now).holds is not False
        if not holds:
            if watch.since_ms >= 0:
                watch.since_ms = -1
                self._kernel.state.touch("governance.path")
            return ""
        if watch.since_ms < 0:
            watch.since_ms = now
            self._kernel.state.touch("governance.path")
        return watch.trigger if now - watch.since_ms >= hold_s * 1000 else ""

    def _premise_lost(self, watch: _Watch, now: int) -> str:
        lost = [
            result
            for result in (self._reader.evaluate(e, age, now) for e, age in watch.premises)
            if result.holds is not True
        ]
        if not lost:
            if watch.lost_since_ms >= 0:
                watch.lost_since_ms = -1
                self._kernel.state.touch("governance.path")
            return ""
        if watch.lost_since_ms < 0:
            watch.lost_since_ms = now
            self._kernel.state.touch("governance.path")
        if now - watch.lost_since_ms < PREMISE_LOSS_HOLD_S * 1000:
            return ""
        first = lost[0]
        state = "not established" if first.holds is None else "no longer holds"
        return f"premise {state}: {first.expr} ({first.detail})"

    # -- reading ------------------------------------------------------------------------

    def records(self) -> list[dict[str, JsonValue]]:
        """Return a copy of every proposal record, oldest first."""
        return copy.deepcopy(self._records)

    def record(self, proposal_id: str) -> dict[str, JsonValue]:
        """Return a copy of one proposal record."""
        for record in self._records:
            if record["proposal_id"] == proposal_id:
                return copy.deepcopy(record)
        raise KeyError(proposal_id)

    def snapshot(self) -> JsonValue:
        """Return every record, the applied-write history, the watches and the mandate register."""
        state = self._snapshot()
        if self._authority is not None:
            # Only once a mandate was set, so a run that never sets one has the
            # state, and the state hash, it had before authority was modelled.
            assert isinstance(state, dict)
            state["authority"] = {
                principal: [[c.time_ms, list(c.contracts), c.by, c.reason] for c in changes]
                for principal, changes in sorted(self._authority.items())
            }
        return state

    def _snapshot(self) -> JsonValue:
        return {
            "records": copy.deepcopy(self._records),
            "notes": list(self.notes),
            "history": [[h.time_ms, h.contract_id, h.tag, h.delta] for h in self._history],
            "watches": [
                [
                    w.proposal_id,
                    w.trigger,
                    w.since_ms,
                    [[t, v] for t, v in w.writes],
                    [[e, a] for e, a in w.premises],
                    w.lost_since_ms,
                    w.undo,
                    list(w.chain),
                ]
                for w in self._watches
            ],
            "unknown": [
                [p, since, [[w.tag, w.value, w.previous] for w in ws]]
                for p, since, ws in self._unknown
            ],
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("control-path snapshot must be a mapping")
        records, history, watches = state["records"], state["history"], state["watches"]
        assert isinstance(records, list) and isinstance(history, list) and isinstance(watches, list)
        self._records = [dict(r) for r in records if isinstance(r, Mapping)]
        notes = state.get("notes", [])
        assert isinstance(notes, list)
        self.notes[:] = [str(n) for n in notes]
        self._history = [
            AppliedWrite(int(str(h[0])), str(h[1]), str(h[2]), float(str(h[3])))
            for h in history
            if isinstance(h, list | tuple)
        ]
        self._watches = []
        for w in watches:
            assert isinstance(w, list | tuple) and isinstance(w[3], list | tuple)
            restore = [(str(t[0]), _scalar(t[1])) for t in w[3] if isinstance(t, list | tuple)]
            watched = w[4] if len(w) > 4 and isinstance(w[4], list | tuple) else []
            premises = [
                (str(t[0]), float(str(t[1]))) for t in watched if isinstance(t, list | tuple)
            ]
            lost = int(str(w[5])) if len(w) > 5 else -1
            undo = str(w[6]) if len(w) > 6 else ""
            kept = w[7] if len(w) > 7 and isinstance(w[7], list | tuple) else []
            self._watches.append(
                _Watch(
                    str(w[0]),
                    str(w[1]),
                    int(str(w[2])),
                    restore,
                    premises,
                    lost,
                    undo,
                    [str(i) for i in kept],
                )
            )
        mandates = state.get("authority")
        self._authority = None
        if isinstance(mandates, Mapping):
            self._authority = {}
            for principal, changes in mandates.items():
                assert isinstance(changes, list | tuple)
                kept = []
                for change in changes:
                    assert isinstance(change, list | tuple) and isinstance(change[1], list | tuple)
                    kept.append(
                        MandateChange(
                            int(str(change[0])),
                            tuple(str(c) for c in change[1]),
                            str(change[2]),
                            str(change[3]),
                        )
                    )
                self._authority[str(principal)] = kept
        self._unknown = []
        for u in state.get("unknown", []):  # type: ignore[union-attr]
            assert isinstance(u, list | tuple) and isinstance(u[2], list | tuple)
            meant = [
                BoundedWrite(str(t[0]), _scalar(t[1]), _scalar(t[2]))
                for t in u[2]
                if isinstance(t, list | tuple)
            ]
            self._unknown.append((str(u[0]), int(str(u[1])), meant))


def _scalar(value: JsonValue) -> bool | int | float | str:
    if not isinstance(value, bool | int | float | str):
        raise ValueError(f"not a point value: {value!r}")
    return value


def decision_fields(decision: Decision) -> dict[str, JsonValue]:
    """Return the fields of a decision that go into a decision record."""
    return {
        "verdict": decision.verdict.value, "decision_ref": decision.decision_ref,
        "contract_id": decision.contract_id, "reasons": list(decision.reasons),
        "expires_at_ms": decision.expires_at_ms, "nonce": decision.single_use_nonce,
        "required_approvers": decision.required_approvers, "escalated": decision.escalated,
    }  # fmt: skip


def _same(a: bool | int | float | str, b: bool | int | float | str) -> bool:
    if isinstance(a, int | float) and isinstance(b, int | float) and not isinstance(a, bool):
        return abs(float(a) - float(b)) < 1e-9
    return a == b
