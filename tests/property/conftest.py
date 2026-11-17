"""A toy simulation built only from kernel primitives.

This model needs no plant. It exercises every kernel service the plant uses
(two task rates, two random streams, events between parts, float state) so
the determinism and snapshot properties are tested on the kernel itself. The
same properties are run on the generic profile in ``test_generic_profile.py``.
"""

from collections.abc import Callable

import pytest

from agentic_datacenter.core.events import Event
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue


class Walker:
    """Fast part: a noisy value that reports each time it crosses a threshold."""

    def __init__(self, kernel: Kernel) -> None:
        self._kernel = kernel
        self._noise = kernel.rng.stream("walker.noise")
        self.value = 20.0
        self.above = False

    def step(self) -> None:
        self.value += self._noise.gauss(0.0, 0.3) + 0.01 * (20.0 - self.value)
        above = self.value > 20.5
        if above != self.above:
            self.above = above
            self._kernel.events.publish("walker.crossed", {"above": above, "value": self.value})

    def snapshot(self) -> JsonValue:
        return {"value": self.value, "above": self.above}

    def restore(self, state: JsonValue) -> None:
        assert isinstance(state, dict)
        value, above = state["value"], state["above"]
        assert isinstance(value, float) and isinstance(above, bool)
        self.value, self.above = value, above


class Integrator:
    """Slow part: integrates the walker once a second and counts its events."""

    def __init__(self, kernel: Kernel, walker: Walker) -> None:
        self._walker = walker
        self._jitter = kernel.rng.stream("integrator.jitter")
        self.total = 0.0
        self.crossings = 0
        self.last_seq = -1
        kernel.events.subscribe("walker.crossed", self._on_crossed)

    def _on_crossed(self, event: Event) -> None:
        self.crossings += 1
        self.last_seq = event.seq

    def step(self) -> None:
        self.total += self._walker.value * (1.0 + self._jitter.uniform(-0.01, 0.01))

    def snapshot(self) -> JsonValue:
        return {"total": self.total, "crossings": self.crossings, "last_seq": self.last_seq}

    def restore(self, state: JsonValue) -> None:
        assert isinstance(state, dict)
        total, crossings, last_seq = state["total"], state["crossings"], state["last_seq"]
        assert isinstance(total, float)
        assert isinstance(crossings, int) and isinstance(last_seq, int)
        self.total, self.crossings, self.last_seq = total, crossings, last_seq


def build_toy(seed: int) -> Kernel:
    """Build a kernel with the two toy parts wired and registered."""
    kernel = Kernel(seed=seed)
    walker = Walker(kernel)
    integrator = Integrator(kernel, walker)
    kernel.state.register("walker", walker)
    kernel.state.register("integrator", integrator)
    kernel.add_task("walker", walker.step)
    kernel.add_task("integrator", integrator.step, period_ms=1000)
    return kernel


# Session scope: the factory holds no state, and hypothesis refuses a
# function-scoped fixture because it is not reset between generated inputs.
@pytest.fixture(scope="session")
def toy() -> Callable[[int], Kernel]:
    """Factory for the toy simulation."""
    return build_toy
