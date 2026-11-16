"""Stub of `electrical.genset`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import ElectricalSupply, FuelDemand, Signal
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """Generator set, fidelity F0.

    The generator never starts: output dead, not ready to load, no fault, no fuel burned.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        self.forward = {
            "output": ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0),
            "ready_to_load": Signal(active=False),
            "fault": Signal(active=False),
        }
        self.reverse = {"fuel": FuelDemand(litre_per_h=0.0)}

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        pass
