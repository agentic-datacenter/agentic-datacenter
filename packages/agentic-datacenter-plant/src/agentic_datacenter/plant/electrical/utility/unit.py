"""One utility incomer, driven by the scenario."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agentic_datacenter.core.io import IOBoard, load_points
from agentic_datacenter.core.module import Inputs, ModuleContext, SimModule
from agentic_datacenter.core.ports import ElectricalDemand, ElectricalSupply
from agentic_datacenter.core.state import JsonValue

from .faults import INPUTS

POINTS = load_points(Path(__file__).parent / "points.yaml")


class Utility(SimModule):
    """Utility incomer at fidelity F1: per-unit voltage and frequency from the scenario."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create an incomer at nominal voltage and frequency."""
        super().__init__(ctx, params)
        self.io = IOBoard(POINTS)

    def step(self, inputs: Inputs) -> None:
        """Record the power drawn."""
        demand = inputs.reverse["supply"]
        assert isinstance(demand, ElectricalDemand)
        self.io["load_kw"] = demand.kw if self.io.number("voltage_pu") > 0.0 else 0.0

    def quiescent(self) -> bool:
        """The incomer changes only when the scenario or its load does."""
        return True

    def forward_outputs(self) -> Mapping[str, object]:
        """Return the supply offered to the switchboard."""
        volts, hertz = self.io.number("voltage_pu"), self.io.number("frequency_pu")
        return {"supply": ElectricalSupply(volts > 0.0, volts, hertz if volts > 0.0 else 0.0)}

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the scenario inputs listed in ``faults.py``."""
        if fault not in INPUTS:
            super().inject(fault, **params)
            return
        if fault == "set":
            for name in ("voltage_pu", "frequency_pu"):
                if name in params:
                    self.io[name] = float(params[name])  # type: ignore[arg-type]
        else:
            level = 0.0 if fault == "loss" else 1.0
            self.io["voltage_pu"] = self.io["frequency_pu"] = level
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the incomer state."""
        return self.io.snapshot()

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        self.io.restore(state)
