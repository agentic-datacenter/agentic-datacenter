"""The fixed-step kernel.

One step: every task that is due runs once, in the order the tasks were added,
and then simulated time moves forward by one base step. A task therefore sees
the time at the start of its step.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from agentic_datacenter.core.clock import SimClock
from agentic_datacenter.core.events import EventBus
from agentic_datacenter.core.rng import RandomStreams
from agentic_datacenter.core.state import JsonValue, StateRegistry, quantized_hash


@dataclass(frozen=True)
class _Task:
    name: str
    run: Callable[[], object]
    every_n_steps: int


class Kernel:
    """Clock, random streams, event bus, state registry and task schedule of one run."""

    def __init__(self, seed: int, step_ms: int = 100) -> None:
        """Create a kernel at time zero.

        Args:
            seed: Run seed; every random stream derives from it.
            step_ms: Base step in simulated milliseconds.
        """
        self.clock = SimClock(step_ms)
        self.rng = RandomStreams(seed)
        self.events = EventBus(self.clock)
        self.state = StateRegistry()
        self.state.register("kernel.clock", self.clock)
        self.state.register("kernel.rng", self.rng)
        self.state.register("kernel.events", self.events)
        self._tasks: list[_Task] = []

    def add_task(self, name: str, run: Callable[[], object], period_ms: int | None = None) -> None:
        """Schedule *run* every *period_ms* of simulated time, starting at time zero.

        Args:
            name: Unique task name.
            run: Called with no arguments each time the task is due.
            period_ms: A positive multiple of the base step; the base step if omitted.

        Raises:
            ValueError: If the name is taken or the period is not a positive
                multiple of the base step.
        """
        step_ms = self.clock.step_ms
        period = step_ms if period_ms is None else period_ms
        if period <= 0 or period % step_ms:
            raise ValueError(f"period_ms must be a positive multiple of {step_ms}, got {period_ms}")
        if any(task.name == name for task in self._tasks):
            raise ValueError(f"task {name!r} is already scheduled")
        self._tasks.append(_Task(name, run, period // step_ms))

    def step(self) -> None:
        """Run the tasks that are due, then advance simulated time by one step."""
        count = self.clock.step_count
        for task in self._tasks:
            if count % task.every_n_steps == 0:
                task.run()
        self.clock.advance()

    def run(self, steps: int) -> None:
        """Take *steps* steps."""
        for _ in range(steps):
            self.step()

    def run_for(self, duration_ms: int) -> None:
        """Run for *duration_ms* of simulated time.

        Raises:
            ValueError: If the duration is negative or not a whole number of steps.
        """
        step_ms = self.clock.step_ms
        if duration_ms < 0 or duration_ms % step_ms:
            raise ValueError(
                f"duration_ms must be a non-negative multiple of {step_ms}, got {duration_ms}"
            )
        self.run(duration_ms // step_ms)

    def snapshot(self) -> dict[str, JsonValue]:
        """Return the complete simulator state."""
        return self.state.snapshot()

    def restore(self, state: Mapping[str, JsonValue]) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        self.state.restore(state)

    def state_hash(self) -> str:
        """Return the hash of the complete simulator state."""
        return self.state.hash()

    def quantized_state_hash(self, digits: int = 9) -> str:
        """Return the state hash with floats rounded, for cross-architecture comparison."""
        return quantized_hash(self.state.snapshot(), digits)
