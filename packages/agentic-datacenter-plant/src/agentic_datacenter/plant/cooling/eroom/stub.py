"""Stub of `cooling.eroom`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import (
    AirHeat,
    AirInlet,
    ElectricalDemand,
    HydronicReturn,
    HydronicSupply,
)
from agentic_datacenter.core.state import JsonValue

WATER_CP_KJ_PER_KG_K = 4.186


class Stub(LatchedModule):
    """Electrical room cooling, fidelity F0.

    All UPS heat is moved to the chilled water while water is available, at a fixed 8 K
    water temperature rise. The room is held at 22 °C. The units draw no power.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        self._delta_t = 8.0
        self.reverse = {
            "chw": HydronicReturn(flow_kg_s=0.0, heat_kw=0.0),
            "ups_heat": AirInlet(inlet_c=22.0),
            "power": ElectricalDemand(kw=0.0),
        }

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        chw, heat = inputs.forward["chw"], inputs.forward["ups_heat"]
        assert isinstance(chw, HydronicSupply) and isinstance(heat, AirHeat)
        removed = heat.heat_kw if chw.available else 0.0
        flow = removed / (WATER_CP_KJ_PER_KG_K * self._delta_t)
        self.reverse["chw"] = HydronicReturn(flow_kg_s=flow, heat_kw=removed)
