"""The event bus.

Delivery is synchronous and in subscription order, so an event has the same
effect in every run. Subscriptions are wiring, made once when the simulation is
built; only the sequence counter is state.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from agentic_datacenter.core.clock import SimClock
from agentic_datacenter.core.state import JsonValue, canonical_bytes


@dataclass(frozen=True)
class Event:
    """One published event."""

    seq: int
    time_ms: int
    topic: str
    payload: Mapping[str, JsonValue]


type Handler = Callable[[Event], object]


class EventBus:
    """Publishes events to the handlers subscribed to their topic."""

    def __init__(self, clock: SimClock) -> None:
        """Create a bus that stamps events with the time of *clock*."""
        self._clock = clock
        self._handlers: dict[str, list[Handler]] = {}
        self._next_seq = 0

    def subscribe(self, topic: str, handler: Handler) -> None:
        """Call *handler* for every later event published on *topic*."""
        self._handlers.setdefault(topic, []).append(handler)

    def publish(self, topic: str, payload: Mapping[str, JsonValue] | None = None) -> Event:
        """Publish an event and deliver it before returning.

        Raises:
            TypeError: If the payload is outside the JSON domain.
            ValueError: If the payload holds a non-finite float.
        """
        body = dict(payload) if payload is not None else {}
        canonical_bytes(body)
        event = Event(seq=self._next_seq, time_ms=self._clock.now_ms, topic=topic, payload=body)
        self._next_seq += 1
        for handler in tuple(self._handlers.get(topic, ())):
            handler(event)
        return event

    def snapshot(self) -> JsonValue:
        """Return the bus state."""
        return {"next_seq": self._next_seq}

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, dict):
            raise ValueError("event-bus snapshot must be a mapping")
        next_seq = state["next_seq"]
        if not isinstance(next_seq, int) or isinstance(next_seq, bool) or next_seq < 0:
            raise ValueError(f"invalid next_seq {next_seq!r}")
        self._next_seq = next_seq
