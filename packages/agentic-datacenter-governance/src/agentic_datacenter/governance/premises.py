"""Premises: what a gate binding establishes about plant state, by reading it itself.

A premise is one of a few fixed forms. There is no expression evaluator behind
them: a form that is not listed here is refused when the contract is loaded.

- ``all(pod.supply_air_c <= 25.0)`` and ``any(...)``: every, or some, instance.
- ``tes.charge_pct >= 80``: every instance of the module (usually there is one).
- ``pod[{pod}].thermally_critical == false``: the instance named by an argument.
- ``all(grid.frequency_pu >= 0.99)``: the utility incomers, for a premise on the grid.
- ``redundancy.chillers >= N_PLUS_1``.
- ``no_active_alarm(priority >= HIGH, system in [CHW, POD])``.

A rollback trigger may end in ``for 120s``: it fires when the condition has
held that long.

A premise holds, does not hold, or cannot be established. The last is the
answer whenever a value it needs is stale, of bad quality, or older than the
premise allows (INV-GOV-3).
"""

from __future__ import annotations

import operator
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace

from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.governance.contracts import Contract, ContractError, fill
from agentic_datacenter.governance.gate import BoundedWrite, PremiseResult, PremiseSnapshot
from agentic_datacenter.supervisory.overview import HIGH, MEDIUM, N_PLUS_1, URGENT, N, Overview
from agentic_datacenter.supervisory.points import PointDatabase, PointRecord

ALIASES = {
    "pod": "cooling.pod", "tes": "cooling.tes", "chw": "cooling.chw_plant",
    "pumps": "cooling.pump_station", "eroom": "cooling.eroom",
    "train": "electrical.power_train", "ups": "electrical.ups",
    "genset": "electrical.genset", "it": "electrical.it_load",
    "grid": "electrical.utility",
}  # fmt: skip
_OPS = {
    "<=": operator.le,
    ">=": operator.ge,
    "==": operator.eq,
    "!=": operator.ne,
    "<": operator.lt,
    ">": operator.gt,
}
_COMPARE = re.compile(
    r"^(?:(?P<q>all|any)\()?(?P<alias>[a-z]+)(?:\[(?P<inst>[^\]]+)\])?\.(?P<point>[a-z0-9_]+)"
    r"\s*(?P<op><=|>=|==|!=|<|>)\s*(?P<rhs>[A-Za-z0-9_.+-]+)\)?$"
)
_REDUNDANCY = re.compile(r"^redundancy\.(?P<system>[a-z]+)\s*>=\s*(?P<level>N_PLUS_1|N)$")
_ALARM = re.compile(
    r"^no_active_alarm\(priority\s*>=\s*(?P<p>URGENT|HIGH|MEDIUM),"
    r"\s*system in \[(?P<systems>[A-Z, ]+)\]\)$"
)
_FOR = re.compile(r"^(?P<expr>.+?)\s+for\s+(?P<seconds>\d+)s$")
_LEVELS = {"N_PLUS_1": N_PLUS_1, "N": N}
_PRIORITIES = {"URGENT": URGENT, "HIGH": HIGH, "MEDIUM": MEDIUM}


def split_hold(expr: str) -> tuple[str, int]:
    """Split ``<condition> for <n>s`` into the condition and the hold time in seconds."""
    match = _FOR.match(expr.strip())
    return (match["expr"], int(match["seconds"])) if match else (expr.strip(), 0)


def check_expr(expr: str) -> None:
    """Refuse an expression that is not one of the supported forms."""
    body, _ = split_hold(expr)
    probe = re.sub(r"\{[a-z_]+\}", "x", body)
    match = _COMPARE.match(probe)
    if match and match["alias"] in ALIASES:
        return
    if _REDUNDANCY.match(probe) or _ALARM.match(probe):
        return
    raise ContractError(f"unsupported premise: {expr!r}")


def _rhs(text: str) -> bool | float | str:
    if text in ("true", "false"):
        return text == "true"
    try:
        return float(text)
    except ValueError:
        return text


class PremiseReader:
    """Reads premises from the supervisory layer, with freshness and quality."""

    def __init__(self, points: PointDatabase, overview: Overview) -> None:
        """Create a reader on the supervisory views."""
        self._points = points
        self._overview = overview

    def _usable(self, records: Sequence[PointRecord], now_ms: int, max_age_s: float) -> str:
        for record in records:
            if record.quality != "good":
                return f"{record.tag} is {record.quality}"
            if now_ms - record.time_ms > max_age_s * 1000:
                return f"{record.tag} is older than {max_age_s:g} s"
        return ""

    def evaluate(
        self, expr: str, max_age_s: float, now_ms: int, invariant: str = ""
    ) -> PremiseResult:
        """Establish one premise at gate time *now_ms*."""
        body, _ = split_hold(expr)
        compare = _COMPARE.match(body)
        if compare and compare["alias"] in ALIASES:
            module_id, point = ALIASES[compare["alias"]], compare["point"]
            if compare["inst"]:
                tag = f"{module_id}[{compare['inst']}].{point}"
                if tag not in self._points.tags():
                    return PremiseResult(expr, None, f"no such point {tag}", invariant)
                records = [self._points.read(tag)]
            else:
                records = self._points.find(module_id, point)
            if not records:
                return PremiseResult(expr, None, f"no {module_id} has a point {point}", invariant)
            problem = self._usable(records, now_ms, max_age_s)
            if problem:
                return PremiseResult(expr, None, problem, invariant)
            test, wanted = _OPS[compare["op"]], _rhs(compare["rhs"])
            try:
                answers = [bool(test(r.value, wanted)) for r in records]
            except TypeError:
                return PremiseResult(expr, None, "values cannot be compared", invariant)
            holds = any(answers) if compare["q"] == "any" else all(answers)
            failing = [r.tag for r, ok in zip(records, answers, strict=True) if not ok]
            detail = "holds" if holds else f"fails for {', '.join(failing[:3])}"
            return PremiseResult(expr, holds, detail, invariant)
        quality, polled_ms = self._points.freshness()
        if quality != "good" or now_ms - polled_ms > max_age_s * 1000:
            return PremiseResult(expr, None, "the supervisory view is stale", invariant)
        redundancy = _REDUNDANCY.match(body)
        if redundancy:
            state = self._overview.redundancy().get(redundancy["system"])
            if state is None or state.quality != "good":
                return PremiseResult(expr, None, "redundancy is not known", invariant)
            holds = state.level >= _LEVELS[redundancy["level"]]
            return PremiseResult(expr, holds, f"{state.system} at {state.level_name}", invariant)
        alarm = _ALARM.match(body)
        if alarm:
            systems = {s.strip() for s in alarm["systems"].split(",")}
            active = [
                a for a in self._overview.active_alarms()
                if a.priority >= _PRIORITIES[alarm["p"]] and a.system in systems
            ]  # fmt: skip
            detail = "no such alarm" if not active else f"active: {active[0].tag}"
            return PremiseResult(expr, not active, detail, invariant)
        return PremiseResult(expr, None, "unsupported premise", invariant)


@dataclass(frozen=True)
class AppliedWrite:
    """One write that was applied through a contract, for rate and cumulative limits."""

    time_ms: int
    contract_id: str
    tag: str
    delta: float


def _check_arguments(
    contract: Contract, arguments: Mapping[str, JsonValue], key_sets: Mapping[str, tuple[str, ...]]
) -> list[str]:
    errors = [
        f"unknown argument {name}" for name in sorted(arguments.keys() - contract.arguments.keys())
    ]
    for name, spec in contract.arguments.items():
        if name not in arguments:
            if spec.authoritative:
                errors.append(f"missing argument {name}")
            continue
        value = arguments[name]
        if spec.type == "number":
            if isinstance(value, bool) or not isinstance(value, int | float) or value != value:
                errors.append(f"{name} must be a number")
        elif spec.type == "key":
            if str(value) not in key_sets.get(spec.key_set or "", ()):
                errors.append(f"{name} must be one of the {spec.key_set}")
        elif spec.type == "choice":
            if str(value) not in (spec.choices or ()):
                errors.append(f"{name} must be one of {list(spec.choices or ())}")
        elif not isinstance(value, str):
            errors.append(f"{name} must be text")
    return errors


def build_snapshot(
    contract: Contract | None,
    arguments: Mapping[str, JsonValue],
    reader: PremiseReader,
    points: PointDatabase,
    key_sets: Mapping[str, tuple[str, ...]],
    history: Sequence[AppliedWrite],
    now_ms: int,
    origins: Mapping[str, float] | None = None,
) -> PremiseSnapshot:
    """Establish everything about one contract instance that a gate decides on.

    *origins* holds, for each point the agent has moved and that is still
    being watched, the value it had before the first of those writes. A step
    that only goes back toward that value, in the contract's safe direction,
    is a restore: rate and cumulative limits are not charged for it
    (INV-GOV-8). Bounds, step and premises are judged as for any other step.
    """
    if contract is None:
        return PremiseSnapshot(time_ms=now_ms, contract_known=False)
    schema_errors = _check_arguments(contract, arguments, key_sets)
    base = PremiseSnapshot(
        time_ms=now_ms,
        contract_known=True,
        risk_tier=contract.risk_tier,
        approval=contract.approval,
        rollback_available=contract.rollback is not None,
    )
    if schema_errors:
        return replace(base, schema_errors=tuple(schema_errors))
    text = {name: str(value) for name, value in arguments.items()}
    writes: list[BoundedWrite] = []
    bound_errors: list[str] = []
    limit_errors: list[str] = []
    directions: set[str] = set()
    safe, origins = contract.safe_direction(), origins or {}
    back: list[bool] = []
    # The step and the range are judged against the present value of each point
    # written, so a value nobody can read leaves the proposal unestablished.
    unreadable: list[PremiseResult] = []
    for write in contract.writes:
        tag = fill(write.tag, text)
        value = arguments[write.value] if write.value is not None else write.const
        assert isinstance(value, bool | int | float | str)
        if tag not in points.tags():
            bound_errors.append(f"range: no such point {tag}")
            continue
        target = points.read(tag)
        previous = target.value
        if target.quality != "good":
            unreadable.append(
                PremiseResult(
                    f"readable({tag})",
                    None,
                    f"the point to be written is {target.quality}",
                    "INV-GOV-3",
                )
            )
        if points.declaration(tag).kind.startswith("analog") and not isinstance(value, bool):
            value = float(value)
        writes.append(BoundedWrite(tag, value, previous))
        if isinstance(value, float) and isinstance(previous, int | float):
            delta = value - float(previous)
            if delta > 0:
                directions.add("increase")
            elif delta < 0:
                directions.add("decrease")
            origin = origins.get(tag)
            back.append(
                safe is not None and origin is not None and delta != 0.0
                and min(float(previous), origin) - 1e-9 <= value
                <= max(float(previous), origin) + 1e-9
                and (delta < 0) == (safe == "decrease")
            )  # fmt: skip
            bounds = write.bounds
            if bounds and not bounds.min <= value <= bounds.max:
                bound_errors.append(
                    f"range: {tag} = {value:g} is outside {bounds.min:g} to {bounds.max:g}"
                )
            if bounds and bounds.max_step is not None and abs(delta) > bounds.max_step + 1e-9:
                bound_errors.append(
                    f"step: {tag} would move {abs(delta):g}, more than {bounds.max_step:g}"
                )
            cumulative = contract.limits.cumulative
            if cumulative:
                since = now_ms - cumulative.window_h * 3_600_000
                moved = sum(abs(h.delta) for h in history if h.tag == tag and h.time_ms > since)
                if moved + abs(delta) > cumulative.max_total_delta + 1e-9:
                    limit_errors.append(
                        f"cumulative: {tag} has moved {moved:g} in {cumulative.window_h:g} h; "
                        f"{abs(delta):g} more would exceed {cumulative.max_total_delta:g}"
                    )
        else:
            back.append(False)
    restore = bool(back) and all(back) and len(back) == len(contract.writes)
    if restore:
        # A step back toward safety is never held back by a limit (INV-GOV-8).
        limit_errors = []
    rate = None if restore else contract.limits.rate
    if rate:
        times = {
            h.time_ms
            for h in history
            if h.contract_id == contract.id and h.time_ms > now_ms - 3_600_000
        }
        if len(times) >= rate.max_per_hour:
            limit_errors.append(f"rate: applied {len(times)} times in the last hour")
    premises = tuple(
        reader.evaluate(fill(p.expr, text), p.max_age_s, now_ms, p.invariant)
        for p in contract.premises
        if p.when == "always" or p.when in directions
    )
    return replace(
        base,
        writes=tuple(writes),
        bound_errors=tuple(bound_errors),
        limit_errors=tuple(limit_errors),
        premises=(*premises, *unreadable),
        restore=restore,
    )
