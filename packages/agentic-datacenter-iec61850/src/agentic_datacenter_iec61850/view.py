"""The relays as views of the point database (SDD 8, 8.5). No protocol library here.

A served value is the sample the point database holds in that step, with its
quality. A data object's timestamp is the relay's own (simulated) time of the
step in which one of its values or its quality last changed.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass

from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.supervisory.points import PointDatabase
from agentic_datacenter_iec61850 import scl
from agentic_datacenter_iec61850.model import EPOCH_MS, Binding, Relay, relays

TOPIC = "net.device_violation"


@dataclass(frozen=True)
class Sample:
    """One served value: what it is, how good it is, and the relay's time for it."""

    value: bool | int | float
    quality: str
    time_ms: int


def convert(value: object, how: str) -> bool | int | float:
    """Return a point value as the attribute bound with conversion *how* serves it."""
    if how == "float":
        return float(value)  # type: ignore[arg-type]
    if how in ("bool", "dbpos"):
        return bool(value)
    if how == "ms":
        return round(float(value) * 1000.0)  # type: ignore[arg-type]
    kind, _, wanted = how.partition(":")
    if kind == "equals":
        return str(value) == wanted
    if kind == "differs":
        return str(value) != wanted
    raise ValueError(f"unknown conversion {how!r}")


class RelayView:
    """Every relay of the facility, its engineering file and its present values."""

    def __init__(self, kernel: Kernel, points: PointDatabase) -> None:
        """Generate the SCD, read it back, and start following the points each step."""
        self._kernel, self._points = kernel, points
        self.relays: dict[str, Relay] = {r.tag: r for r in relays(points)}
        self.scd = scl.scd(list(self.relays.values()))
        self.ieds = {ied.tag: ied for ied in scl.parse(self.scd)}
        self._object: dict[tuple[str, str], str] = {}
        for tag, ied in self.ieds.items():
            for leaf in ied.leaves:
                node, _, path = leaf.ref.partition(".")
                self._object[tag, leaf.ref] = ".".join([node, *path.split(".")[: leaf.depth]])
        self._seen: dict[tuple[str, str], tuple[bool | int | float, str]] = {}
        self._changed_ms: dict[tuple[str, str], int] = {}
        self._listeners: list[Callable[[], None]] = []
        self._guard = threading.Lock()
        self._violations: list[dict[str, JsonValue]] = []
        self.refresh()
        kernel.add_task("iec61850.relays", self.refresh)

    def data_object(self, relay: str, ref: str) -> str:
        """Return the data object that attribute *ref* of *relay* belongs to."""
        return self._object[relay, ref]

    def start_ms(self) -> int:
        """Return the relay time of simulated time zero."""
        return EPOCH_MS

    def _bound(self, binding: Binding) -> tuple[bool | int | float, str]:
        record = self._points.read(binding.tag)
        return convert(record.value, binding.convert), record.quality

    def refresh(self) -> None:
        """Note what changed in this step, then let every running server serve it."""
        now = self._kernel.clock.now_ms
        for tag, relay in self.relays.items():
            for binding in relay.bindings:
                key = (tag, binding.ref)
                current = self._bound(binding)
                if self._seen.get(key) != current:
                    self._seen[key] = current
                    self._changed_ms[tag, self._object[key]] = now
        for listener in tuple(self._listeners):
            listener()

    def follow(self, listener: Callable[[], None]) -> None:
        """Call *listener* after every refresh."""
        self._listeners.append(listener)

    def unfollow(self, listener: Callable[[], None]) -> None:
        """Stop calling *listener*."""
        if listener in self._listeners:
            self._listeners.remove(listener)

    def samples(self, relay: str) -> dict[str, Sample]:
        """Return every bound attribute of *relay* as it stood at the last refresh."""
        out = {}
        for binding in self.relays[relay].bindings:
            value, quality = self._seen[relay, binding.ref]
            changed = self._changed_ms[relay, self._object[relay, binding.ref]]
            out[binding.ref] = Sample(value, quality, EPOCH_MS + changed)
        return out

    def refuse(self, relay: str, service: str, reference: str, client: str, reason: str) -> None:
        """Record a refused request as a device violation event (SDD 8.4, 8.5)."""
        entry: dict[str, JsonValue] = {
            "time_ms": self._kernel.clock.now_ms, "device": relay, "protocol": "mms",
            "service": service, "reference": reference, "client": client, "reason": reason,
        }  # fmt: skip
        with self._guard:
            self._violations.append(entry)
            self._kernel.events.publish(TOPIC, entry)

    def violations(self) -> list[dict[str, JsonValue]]:
        """Return every refused request so far."""
        with self._guard:
            return [dict(entry) for entry in self._violations]
