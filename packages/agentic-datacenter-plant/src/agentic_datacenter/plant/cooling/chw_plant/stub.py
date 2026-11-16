"""Stub of `cooling.chw_plant`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import (
    ElectricalDemand,
    ElectricalSupply,
    HydronicReturn,
    HydronicSupply,
)
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """Chilled water plant, fidelity F0.

    Chilled water is always available at the supply temperature, whatever the heat returned.
    Electrical input is the returned heat divided by a fixed coefficient of performance,
    shared evenly over the power feeds that are energized.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        supply_c = params.get("supply_c", 18.0)
        cop = params.get("cop", 4.0)
        assert isinstance(supply_c, float) and isinstance(cop, float)
        self._cop = cop
        self.forward = {"chws": HydronicSupply(available=True, supply_c=supply_c)}
        self.reverse = {f"power_{n}": ElectricalDemand(kw=0.0) for n in (1, 2, 3)}

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        load = inputs.reverse["chws"]
        assert isinstance(load, HydronicReturn)
        feeds = {name: inputs.forward[name] for name in ("power_1", "power_2", "power_3")}
        live = [n for n, f in feeds.items() if isinstance(f, ElectricalSupply) and f.energized]
        share = load.heat_kw / self._cop / len(live) if live else 0.0
        self.reverse = {name: ElectricalDemand(kw=share if name in live else 0.0) for name in feeds}
