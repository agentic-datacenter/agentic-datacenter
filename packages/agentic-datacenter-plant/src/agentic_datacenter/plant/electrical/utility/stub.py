"""Stub of `electrical.utility`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import ElectricalSupply
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """Utility incomer, fidelity F0.

    The supply is always energized at nominal voltage and frequency. Demand is accepted and
    ignored.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        self.forward = {
            "supply": ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0)
        }

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        pass
