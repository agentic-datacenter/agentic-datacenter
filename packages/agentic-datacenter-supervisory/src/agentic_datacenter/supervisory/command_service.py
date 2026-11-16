"""The Supervisory Command Service: the only component that writes to controllers.

Every write, whoever asks for it, passes the same checks in the same order and
is refused with a distinct reason code at the first one it fails (SDD 8.3,
ADC-SUP-005). A decision reference from a governance gate does not replace
any of them: tier, range and rate are checked again here.

Roles (SDD 7.1):

- ``viewer`` may write nothing.
- ``operator``, ``engineer`` and ``administrator`` may write tier T2 and T3 points.
- ``agent`` may write tier T2 and T3 points only with a decision reference that
  is known, unexpired, unused and matches the tag and value exactly.

Tier T0 and T1 points are never writable here, by anyone.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from dataclasses import dataclass

from agentic_datacenter.core.io import PointValue
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.supervisory.points import PointDatabase

ROLES = ("viewer", "operator", "engineer", "administrator", "agent")
RATE_WINDOW_MS = 60_000


@dataclass(frozen=True)
class Actor:
    """Who is asking: a name and a role, both taken from the authenticated session."""

    name: str
    role: str


@dataclass(frozen=True)
class WriteResult:
    """The outcome of one write request."""

    accepted: bool
    code: str
    old: PointValue | None = None
    new: PointValue | None = None


class CommandService:
    """Checks, executes and logs every supervisory write."""

    def __init__(self, kernel: Kernel, points: PointDatabase, writes_per_minute: int = 10) -> None:
        """Create the service on *points*, with a per-actor rate limit."""
        self._kernel = kernel
        self._points = points
        self._limit = writes_per_minute
        self._log: list[dict[str, JsonValue]] = []
        self._decisions: dict[str, dict[str, JsonValue]] = {}
        self._recent: dict[str, list[int]] = {}
        #: Agent writes still to go unanswered; True when the write lands all the same.
        self._unanswered: list[bool] = []
        kernel.state.register("supervisory.commands", self, tracked=True)

    def authorize(self, decision_ref: str, tag: str, value: PointValue, expires_ms: int) -> None:
        """Register a decision reference a gate issued for one write of *value* to *tag*.

        Raises:
            ValueError: If the reference is already registered.
        """
        if decision_ref in self._decisions:
            raise ValueError(f"decision reference {decision_ref!r} is already registered")
        self._decisions[decision_ref] = {
            "tag": tag, "value": value, "expires_ms": expires_ms, "used": False,
        }  # fmt: skip
        self._kernel.state.touch("supervisory.commands")

    def _check(
        self, tag: str, value: PointValue, actor: Actor, reason: str, decision_ref: str | None
    ) -> str:
        now = self._kernel.clock.now_ms
        if not reason.strip():
            return "REASON_REQUIRED"
        if not self._points.link_up:
            return "LINK_DOWN"
        if tag not in self._points.tags():
            return "UNKNOWN_TAG"
        decl = self._points.declaration(tag)
        if decl.tier in ("T0", "T1"):
            return "TIER_FORBIDDEN"
        if actor.role not in ("operator", "engineer", "administrator", "agent"):
            return "ROLE_FORBIDDEN"
        if decl.problem_with(value) is not None:
            return "OUT_OF_RANGE"
        recent = [t for t in self._recent.get(actor.name, []) if t > now - RATE_WINDOW_MS]
        self._recent[actor.name] = recent
        if len(recent) >= self._limit:
            return "RATE_LIMITED"
        if actor.role != "agent":
            return "OK"
        if decision_ref is None:
            return "DECISION_REQUIRED"
        decision = self._decisions.get(decision_ref)
        if decision is None:
            return "DECISION_UNKNOWN"
        if decision["used"]:
            return "DECISION_USED"
        if now > int(str(decision["expires_ms"])):
            return "DECISION_EXPIRED"
        if decision["tag"] != tag or decision["value"] != value:
            return "DECISION_MISMATCH"
        return "OK"

    def fail_next(self, applied: bool) -> None:
        """Leave the next agent write unanswered (scenario OP-13).

        The write is dispatched and the answer is lost. With *applied* the
        controller took it; without, it did not. Either way the caller gets
        ``TIMEOUT`` and the decision reference is spent.
        """
        self._unanswered.append(applied)
        self._kernel.state.touch("supervisory.commands")

    def write(
        self,
        tag: str,
        value: PointValue,
        actor: Actor,
        reason: str,
        decision_ref: str | None = None,
    ) -> WriteResult:
        """Check, execute and log one write. A refused write changes nothing."""
        now = self._kernel.clock.now_ms
        code = self._check(tag, value, actor, reason, decision_ref)
        old: PointValue | None = None
        new: PointValue | None = None
        lost = code == "OK" and actor.role == "agent" and bool(self._unanswered)
        if lost:
            landed = self._unanswered.pop(0)
            if landed:
                arrived: PointValue = value
                if self._points.declaration(tag).kind.startswith("analog"):
                    arrived = float(value)
                self._points.write_through(tag, arrived)
            if decision_ref is not None:
                self._decisions[decision_ref]["used"] = True
            code = "TIMEOUT"
        if code == "OK":
            written: PointValue = value
            if self._points.declaration(tag).kind.startswith("analog"):
                written = float(value)
            old = self._points.write_through(tag, written)
            new = self._points.read(tag).value
            if new != written:
                code = "READBACK_FAILED"
            else:
                self._recent.setdefault(actor.name, []).append(now)
                if actor.role == "agent" and decision_ref is not None:
                    self._decisions[decision_ref]["used"] = True
        accepted = code == "OK"
        entry: dict[str, JsonValue] = {
            "seq": len(self._log), "time_ms": now, "tag": tag,
            "old": old if accepted else None, "new": new if accepted else None,
            "actor": actor.name, "role": actor.role, "reason": reason,
            "decision_ref": decision_ref, "accepted": accepted, "code": code,
        }  # fmt: skip
        self._log.append(entry)
        self._kernel.state.touch("supervisory.commands")
        self._kernel.events.publish("supervisory.write", {
            "seq": entry["seq"], "tag": tag, "actor": actor.name, "accepted": accepted,
            "code": code,
        })  # fmt: skip
        return WriteResult(accepted, code, old if accepted else None, new if accepted else None)

    def change_log(self) -> list[dict[str, JsonValue]]:
        """Return a copy of the append-only log of every write request, accepted or not."""
        return copy.deepcopy(self._log)

    def snapshot(self) -> JsonValue:
        """Return the log, the registered decision references and the rate counters."""
        return {
            "log": copy.deepcopy(self._log),
            "decisions": copy.deepcopy(self._decisions),
            "recent": {name: list(times) for name, times in self._recent.items()},
            "unanswered": list(self._unanswered),
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("command-service snapshot must be a mapping")
        log, decisions, recent = state["log"], state["decisions"], state["recent"]
        assert isinstance(log, list) and isinstance(decisions, Mapping)
        assert isinstance(recent, Mapping)
        self._log = [dict(entry) for entry in log]
        self._decisions = {str(k): dict(v) for k, v in decisions.items()}  # type: ignore[arg-type]
        self._recent = {str(k): [int(str(t)) for t in v] for k, v in recent.items()}  # type: ignore[union-attr]
        unanswered = state.get("unanswered", [])
        assert isinstance(unanswered, list)
        self._unanswered = [bool(u) for u in unanswered]
