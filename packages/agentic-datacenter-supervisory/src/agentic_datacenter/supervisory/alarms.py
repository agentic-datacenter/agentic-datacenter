"""The alarm engine (SDD 7.5, ADC-SUP-001).

Priorities are urgent (751 to 999), high (501 to 750) and medium (500);
anything lower is a logged event that never appears on the alarm list. An
alarm is in one of four states, from the cross of active or inactive and
acknowledged or not. Analog points have high, low, rate-of-change and
invalid-signal alarms; high and low have a deadband. An alarm is suppressed
during the start-up delay of its equipment and while that equipment is out of
service. Every transition goes to an append-only log.

The engine reads the point database once a second, so with the supervisory
network down it sees stale values, and says so through its invalid-signal
alarms.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol

from agentic_datacenter.core.io import PointValue
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.supervisory.logs import AppendOnlyLog

ACTIVE_UNACKED = "ACTIVE_UNACKED"
ACTIVE_ACKED = "ACTIVE_ACKED"
INACTIVE_UNACKED = "INACTIVE_UNACKED"
INACTIVE_ACKED = "INACTIVE_ACKED"
KINDS = ("discrete", "high", "low", "rate", "invalid")
SCAN_MS = 1000
RATE_WINDOW_S = 60
#: Supply air limits of a POD: the envelope and the thermally critical threshold.
POD_HIGH_C, POD_CRITICAL_C = 27.0, 32.0


def band(priority: int) -> str:
    """Return the priority band of *priority* (SDD 7.5)."""
    if not 1 <= priority <= 999:
        raise ValueError(f"alarm priority must be 1 to 999, not {priority}")
    if priority >= 751:
        return "urgent"
    if priority >= 501:
        return "high"
    return "medium" if priority == 500 else "event"


@dataclass(frozen=True)
class AlarmDef:
    """One alarm on one point.

    Attributes:
        name: Unique id of the alarm.
        tag: The point it watches.
        kind: ``discrete`` (the value is one of ``active_values``), ``high``,
            ``low``, ``rate`` (change per minute, either direction) or
            ``invalid`` (the point's quality is not good).
        priority: 1 to 999; below 500 it is a logged event.
        system: The system it belongs to, for filtering.
        limit: Limit for ``high``, ``low`` and ``rate``.
        deadband: How far inside the limit a ``high`` or ``low`` alarm must
            come before it clears.
        active_values: Values that mean alarm, for ``discrete``.
        running_tag: Point that is true while the equipment runs. The alarm is
            judged only when it has been true for ``startup_delay_s``.
        startup_delay_s: The start-up delay of the equipment.
        out_of_service: A point and the value it has while the equipment is
            out of service; the alarm is suppressed then.
        description: Text shown with the alarm.
    """

    name: str
    tag: str
    kind: str
    priority: int
    system: str = "OTHER"
    limit: float = 0.0
    deadband: float = 0.0
    active_values: tuple[PointValue, ...] = (True,)
    running_tag: str | None = None
    startup_delay_s: int = 0
    out_of_service: tuple[str, PointValue] | None = None
    description: str = ""

    def __post_init__(self) -> None:
        """Check the kind and the priority."""
        if self.kind not in KINDS:
            raise ValueError(f"alarm kind must be one of {', '.join(KINDS)}, not {self.kind!r}")
        band(self.priority)


@dataclass(frozen=True)
class AlarmStatus:
    """One alarm on the alarm list."""

    name: str
    tag: str
    kind: str
    priority: int
    band: str
    system: str
    description: str
    state: str
    since_ms: int
    quality: str


class _Record(Protocol):
    @property
    def value(self) -> PointValue: ...
    @property
    def quality(self) -> str: ...


class _Points(Protocol):
    def read(self, tag: str) -> _Record: ...
    def value_and_quality(self, tag: str) -> tuple[PointValue, str]: ...


class AlarmEngine:
    """Evaluates every alarm definition once a second."""

    def __init__(self, kernel: Kernel, points: _Points, definitions: Sequence[AlarmDef]) -> None:
        """Create the engine and its log, and start scanning.

        Raises:
            ValueError: If two definitions share a name.
        """
        self._kernel, self._points = kernel, points
        self._defs: dict[str, AlarmDef] = {}
        for definition in definitions:
            if definition.name in self._defs:
                raise ValueError(f"alarm {definition.name!r} is defined twice")
            self._defs[definition.name] = definition
        self._state = {name: INACTIVE_ACKED for name in self._defs}
        self._since = {name: 0 for name in self._defs}
        self._quality = {name: "good" for name in self._defs}
        self._running_since: dict[str, int | None] = {
            d.name: None for d in definitions if d.running_tag is not None
        }
        self._history: dict[str, list[float]] = {
            d.name: [] for d in definitions if d.kind == "rate"
        }
        self.log = AppendOnlyLog(kernel, "alarms")
        kernel.state.register("supervisory.alarms", self, tracked=True)
        kernel.add_task("supervisory.alarms", self._scan, period_ms=SCAN_MS)

    # -- evaluation -------------------------------------------------------------------

    def _suppressed(self, d: AlarmDef, now: int) -> bool:
        if d.out_of_service is not None:
            tag, value = d.out_of_service
            if self._points.value_and_quality(tag)[0] == value:
                return True
        if d.running_tag is not None:
            since = self._running_since[d.name]
            if bool(self._points.value_and_quality(d.running_tag)[0]):
                if since is None:
                    since = self._running_since[d.name] = now
            else:
                since = self._running_since[d.name] = None
            if since is None or now - since < d.startup_delay_s * 1000:
                return True
        return False

    def _condition(self, d: AlarmDef, active: bool) -> bool:
        raw, quality = self._points.value_and_quality(d.tag)
        self._quality[d.name] = quality
        if d.kind == "invalid":
            return quality != "good"
        if d.kind == "discrete":
            return raw in d.active_values
        if quality != "good" or isinstance(raw, bool | str):
            if d.kind == "rate":
                self._history[d.name].clear()
            return False
        value = float(raw)
        if d.kind == "high":
            return value >= d.limit - d.deadband if active else value > d.limit
        if d.kind == "low":
            return value <= d.limit + d.deadband if active else value < d.limit
        history = self._history[d.name]
        history.append(value)
        del history[: -(RATE_WINDOW_S + 1)]
        if len(history) <= RATE_WINDOW_S:
            return False
        return abs(history[-1] - history[0]) > d.limit

    def _scan(self) -> None:
        now = self._kernel.clock.now_ms
        changed = bool(self._history)
        for d in self._defs.values():
            state = self._state[d.name]
            was = self._running_since.get(d.name)
            suppressed = self._suppressed(d, now)
            changed = changed or self._running_since.get(d.name) != was
            active = state in (ACTIVE_UNACKED, ACTIVE_ACKED)
            condition = self._condition(d, active) and not suppressed
            if band(d.priority) == "event":
                if condition and not active:
                    self.log.append("event", alarm=d.name, tag=d.tag, priority=d.priority)
                if condition != active:
                    self._state[d.name] = ACTIVE_ACKED if condition else INACTIVE_ACKED
                    changed = True
                continue
            if condition and not active:
                self._set(d, ACTIVE_UNACKED, "raised", now)
                changed = True
            elif not condition and active:
                after = INACTIVE_UNACKED if state == ACTIVE_UNACKED else INACTIVE_ACKED
                self._set(d, after, "suppressed" if suppressed else "cleared", now)
                changed = True
        if changed:
            self._kernel.state.touch("supervisory.alarms")

    def _set(self, d: AlarmDef, state: str, kind: str, now: int, actor: str | None = None) -> None:
        self._state[d.name], self._since[d.name] = state, now
        fields: dict[str, JsonValue] = {
            "alarm": d.name, "tag": d.tag, "priority": d.priority, "state": state,
        }  # fmt: skip
        if actor is not None:
            fields["actor"] = actor
        self.log.append(kind, **fields)
        self._kernel.events.publish("supervisory.alarm", {"alarm": d.name, "state": state})

    # -- for operators -----------------------------------------------------------------

    def definitions(self) -> list[AlarmDef]:
        """Return every alarm definition."""
        return list(self._defs.values())

    def state(self, name: str) -> str:
        """Return the state of alarm *name*.

        Raises:
            KeyError: If there is no such alarm.
        """
        return self._state[name]

    def active(self) -> list[AlarmStatus]:
        """Return the alarm list: everything not inactive and acknowledged, most urgent first."""
        out = []
        for d in self._defs.values():
            state = self._state[d.name]
            if state == INACTIVE_ACKED or band(d.priority) == "event":
                continue
            out.append(
                AlarmStatus(
                    d.name,
                    d.tag,
                    d.kind,
                    d.priority,
                    band(d.priority),
                    d.system,
                    d.description,
                    state,
                    self._since[d.name],
                    self._quality[d.name],
                )
            )
        return sorted(out, key=lambda a: (-a.priority, a.name))

    def acknowledge(self, name: str, actor: str) -> None:
        """Acknowledge alarm *name* as *actor*.

        Raises:
            KeyError: If there is no such alarm.
            ValueError: If the alarm has nothing to acknowledge.
        """
        d, state = self._defs[name], self._state[name]
        if state not in (ACTIVE_UNACKED, INACTIVE_UNACKED) or band(d.priority) == "event":
            raise ValueError(f"alarm {name!r} has nothing to acknowledge")
        after = ACTIVE_ACKED if state == ACTIVE_UNACKED else INACTIVE_ACKED
        self._set(d, after, "acknowledged", self._kernel.clock.now_ms, actor)
        self._kernel.state.touch("supervisory.alarms")

    # -- state ---------------------------------------------------------------------------

    def snapshot(self) -> JsonValue:
        """Return the state of every alarm and what the engine remembers between scans."""
        return {
            "state": dict(self._state),
            "since": dict(self._since),
            "quality": dict(self._quality),
            "running_since": dict(self._running_since),
            "history": {name: list(values) for name, values in self._history.items()},
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("alarm-engine snapshot must be a mapping")
        parts = {key: state[key] for key in ("state", "since", "quality", "running_since")}
        history = state["history"]
        if not all(isinstance(p, Mapping) for p in (*parts.values(), history)):
            raise ValueError("alarm-engine snapshot is malformed")
        self._state = {k: str(v) for k, v in parts["state"].items()}  # type: ignore[union-attr]
        self._since = {k: int(str(v)) for k, v in parts["since"].items()}  # type: ignore[union-attr]
        self._quality = {k: str(v) for k, v in parts["quality"].items()}  # type: ignore[union-attr]
        self._running_since = {
            k: None if v is None else int(str(v))
            for k, v in parts["running_since"].items()  # type: ignore[union-attr]
        }
        self._history = {
            k: [float(str(x)) for x in v]  # type: ignore[union-attr]
            for k, v in history.items()  # type: ignore[union-attr]
        }


class _Database(Protocol):
    def tags(self) -> list[str]: ...
    def read(self, tag: str) -> _Record: ...


_DISCRETE_PRIORITY = {
    "thermally_critical": 900,
    "alarm_lockout": 900,
    "dropped": 900,
    "thermal_trip": 900,
    "leak_alarm": 600,
    "on_battery_alarm": 600,
    "zone_mean_invalid": 600,
}
_SYSTEMS = {
    "cooling.pod": "POD",
    "cooling.chw_plant": "CHW",
    "cooling.pump_station": "CHW",
    "cooling.tes": "CHW",
    "cooling.eroom": "PWR",
    "electrical.power_train": "PWR",
    "electrical.genset": "PWR",
    "electrical.ups": "PWR",
    "electrical.mv_switchgear": "MV",
    "electrical.it_load": "IT",
    "electrical.utility": "MV",
}


def default_alarms(points: _Database) -> list[AlarmDef]:
    """Return the alarm definitions the simulator ships for whatever plant *points* holds.

    Every boolean alarm point, a fault alarm per chiller (suppressed while the
    chiller is disabled, which is how it is taken out of service), and per POD
    a high, a critical and an invalid-signal alarm on supply air. The limits
    are engineering assumptions, like the rest of the plant.
    """
    out = []
    for tag in points.tags():
        name, _, point = tag.rpartition(".")
        system = _SYSTEMS.get(name.split("[", 1)[0], "OTHER")
        if point.startswith("alarm_") or point in _DISCRETE_PRIORITY:
            priority = _DISCRETE_PRIORITY.get(point, 600)
            out.append(AlarmDef(f"{tag}:on", tag, "discrete", priority, system, description=point))
        elif name.startswith("cooling.chw_plant[") and point in (
            "ch1_state",
            "ch2_state",
            "ch3_state",
        ):
            n = point[2]
            out.append(
                AlarmDef(
                    f"{tag}:fault",
                    tag,
                    "discrete",
                    600,
                    "CHW",
                    active_values=("TRIPPED", "LOCKED_OUT"),
                    out_of_service=(f"{name}.ch{n}_enable", False),
                    description=f"Chiller {n} tripped or locked out",
                )  # fmt: skip
            )
        elif name.startswith("cooling.pod[") and point == "supply_air_c":
            out += [
                AlarmDef(
                    f"{tag}:high", tag, "high", 600, "POD", limit=POD_HIGH_C, deadband=0.5,
                    description="Supply air above the envelope",
                ),
                AlarmDef(
                    f"{tag}:critical", tag, "high", 900, "POD", limit=POD_CRITICAL_C, deadband=0.5,
                    description="Supply air thermally critical",
                ),
                AlarmDef(
                    f"{tag}:invalid", tag, "invalid", 600, "POD",
                    description="Supply air reading not valid",
                ),
            ]  # fmt: skip
    return out
