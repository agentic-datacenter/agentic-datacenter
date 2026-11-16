"""Event bus: synchronous, ordered, stamped with simulated time."""

import pytest

from agentic_datacenter.core.clock import SimClock
from agentic_datacenter.core.events import Event, EventBus


def test_publish_stamps_sequence_and_simulated_time() -> None:
    clock = SimClock()
    bus = EventBus(clock)
    first = bus.publish("alarm", {"tag": "A"})
    clock.advance()
    second = bus.publish("alarm", {"tag": "B"})
    assert first == Event(seq=0, time_ms=0, topic="alarm", payload={"tag": "A"})
    assert (second.seq, second.time_ms) == (1, 100)


def test_handlers_run_in_subscription_order() -> None:
    bus = EventBus(SimClock())
    calls: list[str] = []
    bus.subscribe("alarm", lambda e: calls.append("first"))
    bus.subscribe("alarm", lambda e: calls.append("second"))
    bus.publish("alarm")
    assert calls == ["first", "second"]


def test_handler_receives_only_its_topic() -> None:
    bus = EventBus(SimClock())
    seen: list[Event] = []
    bus.subscribe("alarm", seen.append)
    bus.publish("status")
    event = bus.publish("alarm")
    assert seen == [event]


def test_publish_without_payload_gives_an_empty_payload() -> None:
    assert EventBus(SimClock()).publish("alarm").payload == {}


def test_payload_outside_the_json_domain_is_refused() -> None:
    bus = EventBus(SimClock())
    with pytest.raises(TypeError):
        bus.publish("alarm", {"when": object()})  # type: ignore[dict-item]


def test_restore_continues_the_sequence_numbers() -> None:
    bus = EventBus(SimClock())
    bus.publish("alarm")
    saved = bus.snapshot()
    bus.publish("alarm")
    bus.restore(saved)
    assert bus.publish("alarm").seq == 1
