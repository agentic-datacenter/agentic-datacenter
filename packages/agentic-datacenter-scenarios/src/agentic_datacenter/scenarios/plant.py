"""The built-in plant behind the plant interface (ADR 0029, ADC-PLT-001).

The plant is built on the run's kernel and steps with it, as before. Its
state is part of the kernel's snapshot, so a capture of the run holds it and
:meth:`BuiltinPlant.capture` has nothing of its own to give.

The oracle's channels are read from the modules' true state, in the order of
the plant's instances, so every sum is taken in the same order as before.
"""

from __future__ import annotations

import importlib
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version

from agentic_datacenter.core.module import ModuleContractError, SimModule
from agentic_datacenter.core.plant_interface import (
    HARM_CHANNELS,
    Harm,
    PlantDescription,
    PointInfo,
)
from agentic_datacenter.core.profile import Profile, build_plant
from agentic_datacenter.core.registry import ModuleRegistry, Plant
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue, state_hash

#: The kernel state that belongs to the plant (``core/registry.py``).
_PLANT_STATE = ("module.", "ports.", "plant.pending")


def _faults(module: SimModule) -> tuple[str, ...]:
    """Return the faults a module lists in its ``faults.py``, and ``reboot``, which all accept."""
    package = type(module).__module__.rpartition(".")[0]
    try:
        listed = tuple(getattr(importlib.import_module(f"{package}.faults"), "FAULTS", ()))
    except ImportError:
        listed = ()
    return tuple(sorted({*listed, "reboot"}))


class BuiltinPlant:
    """The facility of a profile, built from the installed modules on a run's kernel."""

    def __init__(
        self, profile: Profile, kernel: Kernel, registry: ModuleRegistry | None = None
    ) -> None:
        """Build the plant on *kernel*; it steps with the kernel from now on."""
        self._kernel = kernel
        #: The modules themselves. Only code written for the built-in plant reads them.
        self.modules: Plant = build_plant(
            profile, kernel, registry or ModuleRegistry.from_entry_points()
        )
        self._pods: list[SimModule] = []
        self._loads: list[SimModule] = []
        self._incomers: list[SimModule] = []
        self._trains: list[SimModule] = []
        for _, manifest, module in self.modules.instances():
            {
                "cooling.pod": self._pods,
                "electrical.it_load": self._loads,
                "electrical.mv_switchgear": self._incomers,
                "electrical.power_train": self._trains,
            }.get(manifest.id, []).append(module)

    def describe(self) -> PlantDescription:
        """Return the plant's points, faults, relays and harm channels."""
        points, faults, relays = [], {}, {}
        for name, manifest, module in self.modules.instances():
            zone = manifest.zone_for(module.ctx.instance)
            board = getattr(module, "io", None)
            for point in () if board is None else board:
                decl = board.declaration(point)  # type: ignore[union-attr]
                points.append(
                    PointInfo(
                        f"{name}.{point}", str(decl.kind), decl.tier, decl.unit, decl.range,
                        decl.description, zone,
                    )
                )  # fmt: skip
            faults[name] = _faults(module)
            if manifest.id == "electrical.mv_switchgear":
                for relay in module.relay_tags():  # type: ignore[attr-defined]
                    relays[relay] = (name, zone)
        try:
            built = version("agentic-datacenter-plant")
        except PackageNotFoundError:
            built = "unknown"
        return PlantDescription(
            name="agentic-datacenter built-in plant",
            version=built,
            fidelity="Generic and simulated; F1, not calibrated against a real facility.",
            step_ms=self._kernel.clock.step_ms,
            points=tuple(sorted(points, key=lambda p: p.tag)),
            faults=faults,
            relays=relays,
            harm_channels=HARM_CHANNELS,
            offers_capture=True,
        )

    def harm(self) -> Harm:
        """Return the true state the oracle reads."""
        return Harm(
            supply_air_c=tuple(float(m.ts) for m in self._pods),  # type: ignore[attr-defined]
            it_served_kw=tuple(float(m.io["served_kw"]) for m in self._loads),  # type: ignore[attr-defined]
            it_kwh_lost=tuple(float(m.io["kwh_lost"]) for m in self._loads),  # type: ignore[attr-defined]
            facility_in_kw=tuple(m.power_balance()["in_kw"] for m in self._incomers),  # type: ignore[attr-defined]
            both_closed=tuple(
                bool(m.io["util_brk_closed"] and m.io["gen_brk_closed"])  # type: ignore[attr-defined]
                for m in self._trains
            ),
        )

    def _module(self, target: str) -> SimModule:
        module_id, _, rest = target.partition("[")
        try:
            return self.modules.module(module_id, rest.rstrip("]"))
        except KeyError as error:
            raise ModuleContractError(f"no {target} in this facility") from error

    def write(self, tag: str, value: bool | int | float | str) -> bool | int | float | str:
        """Write a point on its module's board, wake the module, and return the old value."""
        target, _, point = tag.rpartition(".")
        module = self._module(target)
        board = module.io  # type: ignore[attr-defined]
        old: bool | int | float | str = board[point]
        board[point] = value
        module.ctx.wake()
        return old

    def inject(self, target: str, fault: str, params: Mapping[str, JsonValue]) -> None:
        """Inject *fault* into module instance *target*, which refuses a fault it does not know."""
        self._module(target).inject(fault, **params)

    def capture(self) -> JsonValue:
        """Return None: the plant's state is in the kernel's snapshot of the run."""
        return None

    def restore(self, state: JsonValue) -> None:
        """Do nothing: restoring the kernel's snapshot restores the plant."""
        del state

    def state_hash(self) -> str:
        """Return the hash of the plant's part of the kernel state."""
        whole = self._kernel.snapshot()
        return state_hash({k: v for k, v in whole.items() if k.startswith(_PLANT_STATE)})
