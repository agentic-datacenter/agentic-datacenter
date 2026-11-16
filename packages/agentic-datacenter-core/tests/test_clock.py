"""Simulated clock: integer time, no drift, snapshot and restore."""

import pytest

from agentic_datacenter.core.clock import SimClock


def test_starts_at_zero_with_100_ms_default_step() -> None:
    clock = SimClock()
    assert (clock.step_ms, clock.step_count, clock.now_ms) == (100, 0, 0)


def test_advance_adds_exactly_one_step() -> None:
    clock = SimClock(step_ms=100)
    clock.advance()
    assert (clock.step_count, clock.now_ms) == (1, 100)


def test_time_is_exact_after_one_simulated_hour() -> None:
    clock = SimClock(step_ms=100)
    for _ in range(36_000):
        clock.advance()
    assert clock.now_ms == 3_600_000
    assert clock.now_s == 3600.0


@pytest.mark.parametrize("step_ms", [0, -100])
def test_rejects_non_positive_step(step_ms: int) -> None:
    with pytest.raises(ValueError, match="step_ms"):
        SimClock(step_ms=step_ms)


def test_restore_returns_to_the_snapshotted_time() -> None:
    clock = SimClock()
    for _ in range(7):
        clock.advance()
    saved = clock.snapshot()
    for _ in range(5):
        clock.advance()
    clock.restore(saved)
    assert clock.now_ms == 700


def test_restore_refuses_a_snapshot_taken_with_another_step() -> None:
    saved = SimClock(step_ms=100).snapshot()
    with pytest.raises(ValueError, match="step_ms"):
        SimClock(step_ms=50).restore(saved)
