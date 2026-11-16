"""Drive one module instance by hand, with scripted inputs."""

from collections.abc import Callable, Mapping
from typing import Any

from agentic_datacenter.core.module import Inputs, ModuleContext, ModuleEntry
from agentic_datacenter.core.scheduler import Kernel


class ModuleRig:
    """One module instance, a kernel clock, and inputs the test sets directly."""

    def __init__(
        self,
        entry: ModuleEntry,
        params: Mapping[str, Any] | None = None,
        keys: Mapping[str, tuple[str, ...]] | None = None,
        seed: int = 1,
    ) -> None:
        self.kernel = Kernel(seed=seed)
        ctx = ModuleContext(
            entry.manifest.id,
            "X",
            dict(keys or {}),
            self.kernel.clock,
            self.kernel.rng,
            self.kernel.events,
        )
        self.module: Any = entry.factory(ctx, dict(params or {}))
        self.forward: dict[str, object] = {}
        self.reverse: dict[str, object | None] = {}

    @property
    def now_s(self) -> float:
        return self.kernel.clock.now_ms / 1000

    def step(self) -> None:
        inputs = Inputs(forward=dict(self.forward), reverse=dict(self.reverse))
        if self.kernel.clock.now_ms % 1000 == 0:
            self.module.step_slow(inputs)
        self.module.step(inputs)
        self.kernel.clock.advance()

    def run(self, seconds: float) -> None:
        for _ in range(round(seconds * 10)):
            self.step()

    def until(self, condition: Callable[[], bool], limit_s: float = 3600.0) -> float:
        start = self.now_s
        while not condition():
            assert self.now_s - start < limit_s, "condition not reached"
            self.step()
        return self.now_s - start

    def out(self, port: str) -> Any:
        return self.module.forward_outputs()[port]

    def back(self, port: str) -> Any:
        return self.module.reverse_outputs()[port]
