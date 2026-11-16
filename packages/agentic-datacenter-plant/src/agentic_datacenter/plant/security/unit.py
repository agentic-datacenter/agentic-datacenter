"""Physical security signals: an event feed, and nothing that can be commanded."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agentic_datacenter.core.io import IOBoard, load_points
from agentic_datacenter.core.module import Inputs, ModuleContext, SimModule
from agentic_datacenter.core.state import JsonValue

from .faults import FAULTS, KINDS, LATCHED

POINTS = load_points(Path(__file__).parent / "points.yaml")


class Security(SimModule):
    """Physical security at fidelity F1: doors, portals and perimeter zones emit events.

    An event is published on the event bus (topic ``security.event``) with its
    kind and place, and counted. Forced, held and intrusion events hold an
    alarm point until cleared. The module has no ports and no writable point.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create a quiet site."""
        super().__init__(ctx, params)
        self.io = IOBoard(POINTS)

    def step(self, inputs: Inputs) -> None:
        """Nothing happens by itself."""

    def quiescent(self) -> bool:
        """The module only reacts to events."""
        return True

    def forward_outputs(self) -> Mapping[str, object]:
        """The module provides no port."""
        return {}

    def reverse_outputs(self) -> Mapping[str, object]:
        """The module requires no port."""
        return {}

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the events listed in ``faults.py``."""
        if fault not in FAULTS:
            super().inject(fault, **params)
            return
        kind = str(params.get("kind", ""))
        if fault == "clear":
            if kind not in LATCHED:
                raise ValueError(f"kind must be one of {sorted(LATCHED)}")
            self.io[LATCHED[kind]] = False
        else:
            if kind not in KINDS:
                raise ValueError(f"kind must be one of {list(KINDS)}")
            where = str(params.get("where", ""))
            self.io[f"events_{kind}"] = int(self.io[f"events_{kind}"]) + 1
            if kind in LATCHED:
                self.io[LATCHED[kind]] = True
            self.ctx.publish("security.event", {"kind": kind, "where": where})
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state."""
        return {"io": self.io.snapshot()}

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("security snapshot must be a mapping")
        self.io.restore(state["io"])
