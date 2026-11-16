"""Stub of `electrical.power_train`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import ElectricalDemand, ElectricalSupply, Signal
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """LV power train with automatic transfer, fidelity F0.

    The switchboard bus follows the utility feed. The generator is never requested and never
    loaded, so loss of the feed is loss of the bus.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        self.forward = {
            "lv_bus": ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0),
            "gen_start_request": Signal(active=False),
        }
        self.reverse = {
            "utility_feed": ElectricalDemand(kw=0.0),
            "gen_output": ElectricalDemand(kw=0.0),
        }

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        demand = inputs.reverse["lv_bus"]
        assert isinstance(demand, ElectricalDemand)
        self.forward["lv_bus"] = inputs.forward["utility_feed"]
        self.reverse["utility_feed"] = demand
