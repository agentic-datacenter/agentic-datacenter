"""Stub of `cooling.pump_station`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import ElectricalDemand, HydronicReturn, HydronicSupply
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """Chilled water pump station, fidelity F0.

    A pipe: whatever flow the consumers ask for is delivered, with no pump power and no pump
    heat.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        self.forward = {"chw": HydronicSupply(available=False, supply_c=0.0)}
        self.reverse = {
            "chws_in": HydronicReturn(flow_kg_s=0.0, heat_kw=0.0),
            **{f"power_{n}": ElectricalDemand(kw=0.0) for n in (1, 2, 3)},
        }

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        load = inputs.reverse["chw"]
        assert isinstance(load, HydronicReturn)
        self.forward["chw"] = inputs.forward["chws_in"]
        self.reverse["chws_in"] = load
