"""Stub of `fuel`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import ElectricalDemand, FuelSupply
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """Fuel oil system, fidelity F0.

    Fuel is always available to every generator. No tank level, no pump, no power drawn.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        self.forward = {f"supply[{key}]": FuelSupply(available=True) for key in ctx.keys["trains"]}
        self.reverse = {"power": ElectricalDemand(kw=0.0)}

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        pass
