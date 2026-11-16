"""Stub of `electrical.ups`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import AirHeat, ElectricalDemand, ElectricalSupply
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """Uninterruptible power supply, fidelity F0.

    A wire: the output follows the input and the input draws exactly the output demand. No
    battery, no losses, no heat.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        self.forward = {
            "output": ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0),
            "heat": AirHeat(heat_kw=0.0, airflow_kg_s=0.0),
        }
        self.reverse = {"input": ElectricalDemand(kw=0.0)}

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        demand = inputs.reverse["output"]
        assert isinstance(demand, ElectricalDemand)
        self.forward["output"] = inputs.forward["input"]
        self.reverse["input"] = demand
