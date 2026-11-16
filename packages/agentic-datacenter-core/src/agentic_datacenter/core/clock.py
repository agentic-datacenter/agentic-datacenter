"""The simulated clock.

Simulated time is a whole number of milliseconds, so it never drifts. This is
the only module in Agentic-Datacenter that may read the wall clock (ADC-KRN-003).
:func:`wall_seconds` is that one reader. It exists to measure and pace a run
from outside; nothing that affects simulator state may call it.
"""

from __future__ import annotations

import time

from agentic_datacenter.core.state import JsonValue


def wall_seconds() -> float:
    """Return a monotonic wall-clock reading in seconds.

    For measuring how long a run took and, in `compose` mode, pacing it against
    real time. The value must never reach simulator state.
    """
    return time.perf_counter()


class SimClock:
    """Simulated time, advanced one fixed step at a time."""

    def __init__(self, step_ms: int = 100) -> None:
        """Create a clock at time zero.

        Args:
            step_ms: Length of one step in simulated milliseconds.

        Raises:
            ValueError: If *step_ms* is not positive.
        """
        if step_ms <= 0:
            raise ValueError(f"step_ms must be positive, got {step_ms}")
        self._step_ms = step_ms
        self._step_count = 0

    @property
    def step_ms(self) -> int:
        """Length of one step in simulated milliseconds."""
        return self._step_ms

    @property
    def step_count(self) -> int:
        """Number of steps taken since time zero."""
        return self._step_count

    @property
    def now_ms(self) -> int:
        """Simulated time in milliseconds."""
        return self._step_count * self._step_ms

    @property
    def now_s(self) -> float:
        """Simulated time in seconds."""
        return self.now_ms / 1000

    def advance(self) -> None:
        """Move simulated time forward by one step."""
        self._step_count += 1

    def snapshot(self) -> JsonValue:
        """Return the clock state."""
        return {"step_ms": self._step_ms, "step_count": self._step_count}

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`.

        Raises:
            ValueError: If the snapshot was taken with another step length.
        """
        if not isinstance(state, dict):
            raise ValueError("clock snapshot must be a mapping")
        step_ms, step_count = state["step_ms"], state["step_count"]
        if step_ms != self._step_ms:
            raise ValueError(f"snapshot has step_ms {step_ms}, this clock has {self._step_ms}")
        if not isinstance(step_count, int) or isinstance(step_count, bool) or step_count < 0:
            raise ValueError(f"invalid step_count {step_count!r}")
        self._step_count = step_count
