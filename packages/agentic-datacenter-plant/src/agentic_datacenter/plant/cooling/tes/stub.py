"""Stub of `cooling.tes`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import HydronicReturn, HydronicSupply
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """Thermal energy storage, fidelity F0.

    A pipe: water and returned heat pass straight through. Nothing is stored.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        self.forward = {"chws_out": HydronicSupply(available=False, supply_c=0.0)}
        self.reverse = {"chws_in": HydronicReturn(flow_kg_s=0.0, heat_kw=0.0)}

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        load = inputs.reverse["chws_out"]
        assert isinstance(load, HydronicReturn)
        self.forward["chws_out"] = inputs.forward["chws_in"]
        self.reverse["chws_in"] = load
