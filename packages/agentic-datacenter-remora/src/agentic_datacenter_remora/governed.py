"""REMORA's governed execution path as an Agentic-Datacenter gate: the GOVERNED and SHADOW profiles.

Every proposal is first decided by the pure policy function, exactly as in
``DECISION_ONLY``, from premises the control path read itself. A proposal
that survives is then put to REMORA's execution service: ``assess`` records
it and says who must approve, the approvers approve through their own
credentials, and ``execute`` consumes the single-use grant and releases the
call. Only then does the command service write. Bounds come from the signed
ToolSpec, rate and cumulative limits from the signed limit policy, expiry
from simulated time, and everything lands in REMORA's hash-chained audit.

The service runs in this process behind the SDK client, configured only by
environment variables and files, and it is built once: REMORA reads its
configuration when its application module is imported. Runs in one process
therefore share one tenant and keep their limit counters apart by naming
each resource after the run.

At the pinned commit REMORA never accepts a write without a person
(REMORA issue 1233). Under ``GOVERNED`` every write is therefore approved by
at least one operator, including contracts that need none on their own terms.
"""

from __future__ import annotations

import atexit
import copy
import importlib
import json
import os
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, ClassVar

from remora.sdk import (
    DecisionAction,
    RemoraClient,
    RemoraError,
    ToolCall,
    build_postcondition,
    verify_effect,
)

from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.envelope_ref import DECISION_TTL_MS, decision_ref
from agentic_datacenter.governance.gate import (
    AuthenticatedActor,
    Decision,
    GateRefusal,
    Outcome,
    PremiseSnapshot,
    Proposal,
    Verdict,
)
from agentic_datacenter_remora import host_registry, sim_clock
from agentic_datacenter_remora.binding import (
    PinMismatchError,
    RemoraGate,
    check_pin,
    installed_commit,
)
from agentic_datacenter_remora.compile import (
    SCALE,
    TARGET,
    TENANT,
    Compiled,
    compile_contracts,
    derived_secret,
    library_hash,
    restore_tool_id,
)

#: Credential name -> (REMORA role, the principal REMORA records).
PRINCIPALS: dict[str, tuple[str, str]] = {
    "agent": ("operator", "agentic-datacenter-agent"),
    "approver-1": ("domain_expert", "agentic-datacenter-approver-1"),
    "approver-2": ("domain_expert", "agentic-datacenter-approver-2"),
    "approver-3": ("domain_expert", "agentic-datacenter-approver-3"),
    "approver-4": ("domain_expert", "agentic-datacenter-approver-4"),
    "reviewer": ("reviewer", "agentic-datacenter-outcome-reviewer"),
    "verifier": ("effect_verifier", "agentic-datacenter-effect-verifier"),
}
_APPROVERS = {"none": 0, "one_operator": 1, "two_person": 2}
_ACTIONS = {
    DecisionAction.ACCEPT: Verdict.ALLOW,
    DecisionAction.VERIFY: Verdict.VERIFY,
    DecisionAction.ESCALATE: Verdict.VERIFY,
    DecisionAction.ABSTAIN: Verdict.ABSTAIN,
}
Scalar = bool | int | float | str


def _code(exc: Exception) -> str:
    """Return REMORA's refusal as one short line."""
    return " ".join(str(exc).split())[:160] or type(exc).__name__


class GovernedService:
    """REMORA's execution service, in this process, for one contract library."""

    _instance: ClassVar[GovernedService | None] = None

    @classmethod
    def start(cls, library: ContractLibrary) -> GovernedService:
        """Return the service of this process, building it on first use.

        Raises:
            RuntimeError: If the process already runs the service for another
                contract library, or REMORA's application was imported before
                this configuration could be set.
        """
        wanted = library_hash(library)
        if cls._instance is None:
            cls._instance = cls(library)
        elif cls._instance.library_sha256 != wanted:
            raise RuntimeError(
                "REMORA's service reads its configuration once per process; this process "
                "already governs another contract library"
            )
        return cls._instance

    def __init__(self, library: ContractLibrary) -> None:
        """Compile the contracts, set REMORA's configuration and build its application."""
        if "servers.api" in sys.modules:
            raise RuntimeError("REMORA's application was imported before it was configured")
        self.library_sha256 = library_hash(library)
        self.root = Path(tempfile.mkdtemp(prefix="agentic-datacenter-remora-"))
        atexit.register(shutil.rmtree, self.root, True)
        self.compiled: Compiled = compile_contracts(library, self.root / "config")
        manifest = self.compiled.manifest
        tokens = {
            name: "agentic-datacenter-" + derived_secret(library, f"token {name}")
            for name in PRINCIPALS
        }
        table = {
            tokens[name]: {"tenant": TENANT, "role": role, "actor_id": principal}
            for name, (role, principal) in PRINCIPALS.items()
        }
        state, config = self.root / "state", self.root / "config"
        state.mkdir()
        for name in [n for n in os.environ if n.startswith("REMORA_")]:
            del os.environ[name]
        os.environ.update({
            # A host clock is refused in production, and this is not production.
            "REMORA_ENV": "development",
            "REMORA_ENABLED_SURFACES": "execution",
            "REMORA_API_TOKENS": json.dumps(table, sort_keys=True),
            "REMORA_REQUIRE_DISTINCT_APPROVER": "1",
            # A bounded, reversible R1 step inside the signed ToolSpec and limits
            # may run without a person (REMORA #1234). Agentic-Datacenter supplies no semantic
            # bundle, so there is no intent source to resolve; the requirement
            # for one is switched off explicitly (ADR 0016, decision 4).
            "REMORA_BOUNDED_WRITE_ACCEPT": "1",
            "REMORA_BOUNDED_WRITE_REQUIRE_INTENT": "0",
            # REMORA's own rate limiter counts on the wall clock; rates are in the limit policy.
            "REMORA_EXECUTION_RATE_LIMIT_PER_MIN": "0",
            "REMORA_PDP_SIGNING_KEY": derived_secret(library, "pdp key"),
            "REMORA_LEASE_SIGNING_KEY": derived_secret(library, "lease key"),
            "REMORA_AUDIT_SIGNING_KEY": derived_secret(library, "audit key"),
            "REMORA_ENVELOPE_SIGNING_KEY": derived_secret(library, "envelope key"),
            "REMORA_CHAIN_DB": str(state / "execution.db"),
            # On disk with the other ledgers, so that a snapshot of the state
            # directory is all of REMORA's state (snapshot_state).
            "REMORA_CONTROL_PLANE_DB": str(state / "control-plane.db"),
            "REMORA_TOOL_REGISTRY_MODULE": host_registry.__name__,
            "REMORA_TOOL_METADATA_FILE": str(config / "tool_metadata.json"),
            "REMORA_TOOLSPEC_BUNDLE": str(config / "toolspec-bundle.json"),
            "REMORA_TOOLSPEC_VERIFY_KEYS": str(manifest["toolspec_verify_key"]),
            "REMORA_TOOLSPEC_PINNED_DIGEST": str(manifest["toolspec_pinned_digest"]),
            "REMORA_LIMITS_FILE": str(config / "limits.json"),
            "REMORA_LIMITS_LEDGER": str(state / "limits-ledger.db"),
            "REMORA_LIMITS_TRUSTED_KEYS": str(manifest["limits_public_key"]),
            "REMORA_REQUIRE_LIMITS": "1",
            "REMORA_LIMITS_OBSERVER_MODULE": host_registry.__name__,
            "REMORA_LIMITS_EVIDENCE_MODULE": host_registry.__name__,
            "REMORA_TIME_SOURCE_MODULE": sim_clock.__name__,
        })  # fmt: skip
        host_registry.TOOL_IDS[:] = list(manifest["tools"])
        # The application object is REMORA's documented entry point
        # (``uvicorn servers.api:app``); nothing else of that module is used.
        application = importlib.import_module("servers.api").app
        from starlette.testclient import TestClient  # noqa: PLC0415 - only with the service

        self._http = TestClient(application)
        # The client class is loaded lazily by the SDK, so a type checker sees a value.
        client: Any = RemoraClient
        self.clients: dict[str, Any] = {
            name: client(base_url="http://testserver", token=token, http_client=self._http)
            for name, token in tokens.items()
        }
        self._slots: dict[str, str] = {}
        self._runs = 0
        self.state = state

    def next_run(self) -> str:
        """Return a name for one more run, to keep its limit counters apart."""
        self._runs += 1
        return f"run-{self._runs:05d}"

    def approver(self, name: str) -> Any:
        """Return the credential of the person *name*, assigning one on first use."""
        if name not in self._slots:
            free = [s for s in PRINCIPALS if s.startswith("approver-")][len(self._slots) :]
            if not free:
                raise GateRefusal("no credential left for another approver")
            self._slots[name] = free[0]
        return self.clients[self._slots[name]]

    def principal_of(self, name: str) -> str:
        """Return the principal REMORA records for the person *name*."""
        return PRINCIPALS[self._slots[name]][1]


@dataclass
class _Pending:
    """What the gate keeps about one proposal REMORA has assessed."""

    remora_proposal: str
    call: ToolCall
    review_item: str | None
    token: Mapping[str, Any] | None
    #: The REMORA tool: the contract, or its restore tool.
    tool: str
    tag: str
    target: str
    expected: Scalar
    tool_call_hash: str
    approvers: tuple[str, ...] = ()
    operation: str = ""
    effect: str = ""


class GovernedRemoraGate:
    """REMORA deciding, authorizing and releasing each write."""

    name = "remora_governed"
    profile = "GOVERNED"
    #: Rate and cumulative limits are REMORA's to enforce; the control path only reports its own.
    enforces_limits = True
    #: REMORA's ledgers are not part of the simulator's state: a replay cannot be
    #: restored from a capture alone. It is restored with :meth:`restore_state`.
    restorable = False
    _values: ClassVar[dict[str, float]] = {}
    #: While a call is being executed, its point is read live: REMORA looks again after dispatch.
    _readers: ClassVar[dict[str, Callable[[], Scalar]]] = {}
    _evidence: ClassVar[dict[str, bool]] = {}

    def __init__(
        self, contracts: ContractLibrary, pin_file: Path | None = None, verify_pin: bool = True
    ) -> None:
        """Start (or join) the service of this process.

        Raises:
            PinMismatchError: If the installed REMORA is not the pinned commit
                (ADC-PIN-003). ``verify_pin=False`` is for tests of the
                mechanism only; a result from such a run is not reportable.
        """
        self.remora_commit: str | None = installed_commit()
        if verify_pin:
            pin = pin_file or Path(os.environ.get("ADC_REMORA_PIN", "REMORA_PIN"))
            if not pin.is_file():
                raise PinMismatchError(f"no REMORA_PIN at {pin.resolve()}; cannot check the pin")
            self.remora_commit = check_pin(pin)
        self._service = GovernedService.start(contracts)
        self._run = self._service.next_run()
        self._pure = RemoraGate()
        self._pending: dict[str, _Pending] = {}
        self.outcomes: dict[str, Outcome] = {}
        host_registry.OBSERVE = self._present_value
        host_registry.EVIDENCE = self._evidence.__getitem__

    def installed_commit(self) -> str | None:
        """Return the commit of the REMORA that is installed, for an evidence bundle."""
        return self.remora_commit

    # -- deciding ------------------------------------------------------------------

    def evaluate(
        self, proposal: Proposal, premises: PremiseSnapshot, actor: AuthenticatedActor
    ) -> Decision:
        """Decide on *proposal*, and put it to REMORA's service when it can go on."""
        pure = self._pure.evaluate(proposal, premises, actor)
        detail: dict[str, Any] = {
            "profile": self.profile,
            "pure_decision": pure.verdict.value,
            "tool_call_hash": dict(pure.detail).get("tool_call_hash", ""),
        }
        if pure.verdict in (Verdict.DENY, Verdict.ABSTAIN) or not premises.writes:
            return replace(pure, detail=detail)
        first = premises.writes[0]
        target = f"{self._run}|{first.tag}"
        self._observe(target, first.previous)
        arguments = {**json.loads(json.dumps(dict(proposal.arguments))), "target": target}
        # A step back toward where the agent started is assessed under the
        # contract's restore tool: same bounds, no limit charged (INV-GOV-8).
        tool = restore_tool_id(proposal.contract_id) if premises.restore else proposal.contract_id
        detail["tool"] = tool
        call = ToolCall(
            tool_name=tool,
            arguments=arguments,
            target_environment=TARGET,
            schema_valid=not premises.bound_errors,
            rollback_available=premises.rollback_available,
        )
        sim_clock.set_ms(premises.time_ms)
        reasons = [r for r in pure.reasons if not r.startswith("remora:")]
        try:
            result = self._service.clients["agent"].assess(call)
        except RemoraError as exc:
            reasons.insert(0, f"remora:{_code(exc)}")
            return self._decision(proposal, premises, Verdict.DENY, reasons, 0, False, detail)
        verdict = _ACTIONS.get(result.action, Verdict.DENY)
        reasons = [f"remora:{reason}" for reason in result.reasons] + reasons
        needed = _APPROVERS.get(premises.approval, 0)
        approvers = 0
        if verdict is Verdict.VERIFY:
            asked = int(str(result.raw.get("approvals_required") or 1))
            approvers = max(needed, asked, 1)
            if needed > asked:
                reasons.append(f"contract requires {premises.approval}")
        elif verdict is Verdict.ALLOW and needed:
            # An accepted proposal has no review item, so nobody could approve it.
            verdict = Verdict.DENY
            reasons.append(f"contract requires {premises.approval}; REMORA asked for nobody")
        escalated = result.action is DecisionAction.ESCALATE
        detail.update({
            "remora_action": result.action.value,
            "remora_proposal_id": result.proposal_id,
            "remora_tool_call_hash": result.tool_call_hash,
            "toolspec_enforced": bool(result.toolspec and result.toolspec.enforced),
        })  # fmt: skip
        decision = self._decision(
            proposal, premises, verdict, reasons, approvers, escalated, detail
        )
        if verdict in (Verdict.ALLOW, Verdict.VERIFY):
            self._pending[decision.decision_ref] = _Pending(
                result.proposal_id, call, result.review_item_id, result.execution_token,
                tool, first.tag, target, first.value, result.tool_call_hash,
            )  # fmt: skip
        return decision

    @classmethod
    def _present_value(cls, target: str) -> float:
        """Return the value of the point a limit is kept under, in whole ledger units."""
        reader = cls._readers.get(target)
        value = reader() if reader is not None else cls._values[target]
        return round(float(value) * SCALE) / SCALE

    def _observe(self, target: str, value: Scalar) -> None:
        """Remember the present value of a point for REMORA's movement meter."""
        if isinstance(value, int | float) and not isinstance(value, bool):
            # The ledger counts in whole units of 1 / SCALE.
            self._values[target] = round(float(value) * SCALE) / SCALE

    def _decision(
        self,
        proposal: Proposal,
        premises: PremiseSnapshot,
        verdict: Verdict,
        reasons: list[str],
        approvers: int,
        escalated: bool,
        detail: Mapping[str, Any],
    ) -> Decision:
        """Build the decision. Its reference holds nothing REMORA draws at random."""
        writes = [[w.tag, w.value] for w in premises.writes]
        ref = decision_ref(
            self.name, proposal.proposal_id, proposal.contract_id, verdict.value,
            [writes, str(detail.get("tool_call_hash", ""))], reasons, premises.time_ms,
        )  # fmt: skip
        allowed = verdict is Verdict.ALLOW
        return Decision(
            verdict=verdict,
            decision_ref=ref,
            contract_id=proposal.contract_id,
            bounded_writes=premises.writes if allowed else (),
            expires_at_ms=premises.time_ms + DECISION_TTL_MS,
            single_use_nonce=ref[-12:],
            reasons=tuple(reasons) or ("remora:accept",),
            required_approvers=approvers,
            escalated=escalated,
            detail=dict(detail),
        )

    # -- approving -----------------------------------------------------------------

    def approve(self, decision_ref: str, approver: str, now_ms: int) -> None:
        """Record one person's approval with REMORA, under that person's own credential.

        Raises:
            GateRefusal: If REMORA does not take the approval.
        """
        pending = self._known(decision_ref)
        if pending.review_item is None:
            raise GateRefusal("nothing to approve")
        sim_clock.set_ms(now_ms)
        try:
            self._service.approver(approver).approve(pending.review_item, on_behalf_of=approver)
        except RemoraError as exc:
            raise GateRefusal(f"remora:{_code(exc)}") from exc
        pending.approvers = (*pending.approvers, self._service.principal_of(approver))

    def reject(self, decision_ref: str, approver: str, reason: str, now_ms: int) -> None:
        """Tell REMORA that a person refused the proposal."""
        pending = self._pending.get(decision_ref)
        if pending is None or pending.review_item is None:
            return
        sim_clock.set_ms(now_ms)
        try:
            self._service.approver(approver).reject(pending.review_item, reason=reason)
        except RemoraError as exc:
            raise GateRefusal(f"remora:{_code(exc)}") from exc

    def _known(self, decision_ref: str) -> _Pending:
        pending = self._pending.get(decision_ref)
        if pending is None:
            raise GateRefusal("REMORA holds no authorization under this reference")
        return pending

    # -- executing -----------------------------------------------------------------

    def execute(
        self,
        decision_ref: str,
        now_ms: int,
        apply: Callable[[], tuple[str, str]],
        read: Callable[[str], Scalar],
    ) -> Outcome:
        """Have REMORA consume the grant and release the call; *apply* writes when it does.

        *apply* is called at most once, from inside REMORA's dispatch. If REMORA
        refuses, nothing is written. A write the command service refused, or one
        it did not answer, leaves REMORA holding the outcome as unknown.
        """
        try:
            pending = self._known(decision_ref)
        except GateRefusal as exc:
            return Outcome("REJECTED", str(exc))
        said: dict[str, str] = {}

        def dispatch(arguments: Mapping[str, Any]) -> dict[str, Any]:
            if dict(arguments) != dict(pending.call.arguments):
                raise RuntimeError("REMORA released a call other than the one that was assessed")
            said["status"], said["detail"] = apply()
            if said["status"] != "APPLIED":
                raise RuntimeError(said["detail"])
            return {"applied": True}

        self._observe(pending.target, read(pending.tag))
        if pending.target in self._values:
            self._readers[pending.target] = lambda: read(pending.tag)
        sim_clock.set_ms(now_ms)
        host_registry.DISPATCH = dispatch
        agent = self._service.clients["agent"]
        try:
            if pending.token is not None:
                result: Any = agent.execute_accepted(pending.token, pending.call)
            else:
                assert pending.review_item is not None
                result = agent.execute(pending.review_item, pending.call)
        except RemoraError as exc:
            return Outcome("REJECTED", f"remora:{_code(exc)}")
        finally:
            host_registry.DISPATCH = None
            self._readers.pop(pending.target, None)
        execution = getattr(result, "tool_execution", None)
        if execution is None and str(result.outcome) != "execute":
            return Outcome("REJECTED", f"remora:{result.outcome}")
        execution = dict(execution or {})
        if execution.get("executed"):
            pending.effect = self._record_effect(pending, result, read)
            return Outcome("APPLIED", f"remora effect: {pending.effect}")
        if not said:
            # REMORA refused before dispatch: nothing was written.
            return Outcome("REJECTED", f"remora:{execution.get('refusal_reason', result.outcome)}")
        pending.operation = self._held_operation(pending)
        if said["status"] == "REJECTED":
            # The command service answered, and its answer was no. Return what
            # the call reserved, on that statement, through REMORA's reviewer.
            self.resolve_unknown(decision_ref, False, now_ms)
            return Outcome("REJECTED", said["detail"])
        return Outcome("UNKNOWN", said["detail"])

    def _record_effect(self, pending: _Pending, result: Any, read: Callable[[str], Scalar]) -> str:
        """Read the point back and hand REMORA what was seen. Return the recorded status."""
        observed = {"value": read(pending.tag)}
        spec = build_postcondition(
            tool_id=pending.tool,
            target_selector={"tag": pending.target},
            expected_fields={"value": pending.expected},
        )
        grant, toolspec = result.execution_grant or {}, result.toolspec
        view = verify_effect(
            spec,
            observed,
            proposal_id=pending.remora_proposal,
            execution_id=str(grant.get("jti", "")),
            toolspec_hash=str(getattr(toolspec, "hash", "") or ""),
            verifier_identity=PRINCIPALS["verifier"][1],
        )
        try:
            recorded = self._service.clients["verifier"].record_effect(
                pending.remora_proposal, view, observed=observed, arguments=pending.call.arguments
            )
        except RemoraError as exc:
            return f"not recorded ({_code(exc)})"
        status = getattr(recorded.status, "value", recorded.status)
        return f"{status} ({recorded.verdict_source})"

    def _held_operation(self, pending: _Pending) -> str:
        """Return the id of the unknown outcome REMORA now holds for *pending*."""
        mine = {p.operation for p in self._pending.values()}
        try:
            held = self._service.clients["reviewer"].list_unresolved()
        except RemoraError:
            return ""
        for operation in held:
            if operation.tool == pending.tool and operation.operation_id not in mine:
                return str(operation.operation_id)
        return ""

    def resolve_unknown(self, decision_ref: str, executed: bool, now_ms: int) -> str:
        """Resolve an unknown outcome from an independent read of the plant.

        The reviewer is a principal other than the agent, and the statement is
        checked by REMORA through this deployment's evidence module.
        """
        pending = self._pending.get(decision_ref)
        if pending is None or not pending.operation:
            return "nothing held by REMORA"
        evidence = f"plant-read:{pending.target}:{pending.operation}"
        self._evidence[evidence] = executed
        sim_clock.set_ms(now_ms)
        try:
            self._service.clients["reviewer"].resolve_unknown(
                pending.operation,
                executed=executed,
                evidence_ref=evidence,
                reason="independent read of plant state after an unanswered write",
            )
        except RemoraError as exc:
            return f"not resolved ({_code(exc)})"
        return "resolved"

    def record_outcome(self, decision_ref: str, outcome: Outcome) -> None:
        """Keep what became of a decision, for the evidence of the run."""
        self.outcomes[decision_ref] = outcome

    # -- snapshot -------------------------------------------------------------------

    def snapshot_state(self) -> dict[str, Any]:
        """Return everything REMORA and this binding keep, to come back to this instant.

        REMORA's state is its SQLite ledgers, all in one directory, and the
        binding's own records. A counterfactual branch restored from this is
        checked against a branch replayed from the start (ADC-BEN-003).
        """
        root = self._service.state
        return {
            "files": {
                str(p.relative_to(root)): p.read_bytes() for p in sorted(root.rglob("*"))
                if p.is_file()
            },
            "run": self._run,
            "pending": {ref: copy.copy(p) for ref, p in self._pending.items()},
            "outcomes": dict(self.outcomes),
            "values": dict(self._values),
            "evidence": dict(self._evidence),
            "slots": dict(self._service._slots),
        }  # fmt: skip

    def restore_state(self, snapshot: Mapping[str, Any]) -> None:
        """Put back what :meth:`snapshot_state` returned, in this process.

        Each ledger is rewritten in place, so a connection REMORA holds open
        reads the restored file at its next transaction, as it would after a
        write by another process.

        Raises:
            RuntimeError: If REMORA created a file after the snapshot was taken;
                such a state cannot be put back.
        """
        root = self._service.state
        files: Mapping[str, bytes] = snapshot["files"]
        present = {str(p.relative_to(root)) for p in root.rglob("*") if p.is_file()}
        if present - set(files):
            raise RuntimeError(f"REMORA created files after the snapshot: {present - set(files)}")
        for name, data in files.items():
            with (root / name).open("r+b" if name in present else "wb") as handle:
                handle.write(data)
                handle.truncate()
        self._run = str(snapshot["run"])
        self._pending = {ref: copy.copy(p) for ref, p in snapshot["pending"].items()}
        self.outcomes = dict(snapshot["outcomes"])
        self._values.clear()
        self._values.update(snapshot["values"])
        self._evidence.clear()
        self._evidence.update(snapshot["evidence"])
        self._service._slots = dict(snapshot["slots"])

    # -- evidence ------------------------------------------------------------------

    def evidence(self) -> dict[str, Any]:
        """Return what ties this run to REMORA's own records.

        Proposal ids, tokens and audit hashes differ from run to run by
        REMORA's design, so they are kept here and out of the state hash.
        """
        chain = self._service.clients["agent"].verify_audit_chain()
        return {
            "profile": self.profile,
            "remora_commit": self.remora_commit,
            "artifacts": self._service.compiled.manifest,
            "audit_chain": {
                "valid": chain.valid,
                "records_checked": chain.records_checked,
                "problems": list(chain.problems),
            },
            "proposals": [
                {
                    "decision_ref": ref,
                    "remora_proposal_id": p.remora_proposal,
                    "tool_call_hash": p.tool_call_hash,
                    "approved_by": list(p.approvers),
                    "effect": p.effect,
                    "outcome": self.outcomes[ref].status if ref in self.outcomes else "",
                }
                for ref, p in self._pending.items()
            ],
        }


class ShadowRemoraGate(GovernedRemoraGate):
    """REMORA assessing every proposal, with nothing executed (the SHADOW profile)."""

    name = "remora_shadow"
    profile = "SHADOW"


def create(contracts: ContractLibrary) -> GovernedRemoraGate:
    """Build the governed gate for a run. The installed REMORA must be the pinned commit."""
    return GovernedRemoraGate(contracts)


def create_shadow(contracts: ContractLibrary) -> ShadowRemoraGate:
    """Build the shadow gate for a run. The installed REMORA must be the pinned commit."""
    return ShadowRemoraGate(contracts)
