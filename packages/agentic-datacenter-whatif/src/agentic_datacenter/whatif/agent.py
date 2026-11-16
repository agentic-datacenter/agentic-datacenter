"""The goal-seeking agent of the governed branch (ADR 0019, decision 3).

It is not one of the benchmark agents. It has one goal, a value for the one
number a contract takes, and it pursues it only through the agent tool
surface: it reads the written point and the contract, and proposes contract
instances. It never asks for what the contract's published limits already rule
out, and it records at every decision point what it did and why, so the
branch can say how far it got and why it stopped.

Premises are not pre-filtered: whether they hold is the gate's to establish,
and a refusal on them is recorded with the gate's reasons.
"""

from __future__ import annotations

import math
from typing import Any

from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.governance.agent_tools.server import AgentTools

EPS = 1e-9
HOUR_MS = 3_600_000
#: A proposal that still counts against the contract's limits.
_COUNTED = ("APPLIED", "ROLLED_BACK", "UNKNOWN")


def _number(value: JsonValue) -> float:
    return float(str(value))


class GoalSeekingAgent:
    """Moves one contract argument toward a target, one permitted step at a time."""

    name = "goal_seeking"

    def __init__(self, contract_id: str, argument: str, target: float) -> None:
        """Pursue *target* for *argument* of *contract_id*."""
        self.contract_id, self.argument, self.target = contract_id, argument, target
        self.log: list[dict[str, JsonValue]] = []

    def _counted(self, tools: AgentTools) -> list[dict[str, JsonValue]]:
        return [
            r for r in tools.list_my_proposals()
            if r["contract_id"] == self.contract_id
            and (r["outcome"] in _COUNTED or r["outcome_detail"] == "waiting for approval")
        ]  # fmt: skip

    def _held_back(
        self, tools: AgentTools, contract: dict[str, Any], step: float, read_ms: int
    ) -> tuple[float, str]:
        """Return the step the published limits leave room for, and why it is smaller."""
        limits = contract.get("limits") or {}
        mine = self._counted(tools)
        cumulative = limits.get("cumulative")
        if isinstance(cumulative, dict):
            window_ms = _number(cumulative["window_h"]) * HOUR_MS
            allowed = _number(cumulative["max_total_delta"])
            moved = 0.0
            for record in mine:
                writes = record["writes"]
                recent = read_ms - int(str(record["time_ms"])) < window_ms
                if recent and isinstance(writes, list) and writes:
                    first = writes[0]
                    assert isinstance(first, list)
                    moved += abs(_number(first[1]) - _number(first[2]))
            room = allowed - moved
            if room <= EPS:
                return 0.0, (
                    f"cumulative limit: {moved:g} of {allowed:g} moved within "
                    f"{_number(cumulative['window_h']):g} h"
                )
            if abs(step) > room + EPS:
                step = math.copysign(room, step)
        rate = limits.get("rate")
        if isinstance(rate, dict):
            recent_calls = [r for r in mine if int(str(r["time_ms"])) > read_ms - HOUR_MS]
            per_hour = int(str(rate["max_per_hour"]))
            if len(recent_calls) >= per_hour:
                return 0.0, f"rate limit: {per_hour} calls in the last hour, {per_hour} allowed"
        return step, ""

    def decide(self, tools: AgentTools, now_s: int) -> None:
        """Take one permitted step toward the target, or record why not."""
        contract = tools.describe_contract(self.contract_id)
        writes = contract.get("writes")
        assert isinstance(writes, list) and writes and isinstance(writes[0], dict)
        tag = str(writes[0]["tag"])
        bounds = writes[0].get("bounds")
        point = tools.get_points([tag])[0]
        value, read_ms = _number(point["value"]), int(str(point["time_ms"]))
        entry: dict[str, JsonValue] = {"t_s": now_s, "value_before": value}
        self.log.append(entry)
        if abs(self.target - value) <= EPS:
            entry.update({"action": "held back", "reason": "target reached"})
            return
        step = self.target - value
        if isinstance(bounds, dict) and bounds.get("max_step") is not None:
            step = math.copysign(min(abs(step), _number(bounds["max_step"])), step)
        step, reason = self._held_back(tools, contract, step, read_ms)
        if reason:
            entry.update({"action": "held back", "reason": reason})
            return
        proposed = round(value + step, 6)
        record = tools.propose_action(
            self.contract_id,
            {self.argument: proposed},
            rationale=f"what-if: toward {self.argument} = {self.target:g}",
        )
        entry.update({
            "action": "proposed", "value": proposed, "proposal_id": record["proposal_id"],
            "verdict": record["verdict"], "outcome": record["outcome"],
            "outcome_detail": record["outcome_detail"], "reasons": record["reasons"],
        })  # fmt: skip

    def snapshot(self) -> JsonValue:
        """Return the log, which is all the agent remembers."""
        return {"log": [dict(e) for e in self.log]}

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        assert isinstance(state, dict) and isinstance(state["log"], list)
        self.log = [dict(e) for e in state["log"] if isinstance(e, dict)]


def stopped_because(log: list[dict[str, JsonValue]], reached: bool) -> list[str]:
    """Return why the agent ended where it did, from its log.

    The reasons it held back for, and the gate's reasons for any proposal that
    did not apply, after the last step that did. Each reason once, in order.
    """
    if reached:
        return ["target reached"]
    last = max(
        (i for i, e in enumerate(log) if e.get("outcome") in ("APPLIED", "ROLLED_BACK")),
        default=-1,
    )
    out: list[str] = []
    for entry in log[last + 1 :]:
        found: list[str] = []
        if entry.get("action") == "held back":
            found.append(str(entry["reason"]))
        elif entry.get("outcome") not in ("APPLIED", "ROLLED_BACK"):
            reasons = entry.get("reasons")
            detail = str(entry.get("outcome_detail") or entry.get("outcome"))
            listed = [str(r) for r in reasons] if isinstance(reasons, list) else []
            found.append(f"{entry.get('verdict')}: {detail}; " + ", ".join(listed))
        out += [r for r in found if r not in out]
    return out or ["the run ended before the target was reached"]
