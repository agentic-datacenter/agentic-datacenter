"""Stub of `electrical.mv_switchgear`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import ElectricalDemand, ElectricalSupply
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """36 kV switchboard, fidelity F0.

    Every feeder follows incomer 1 while it is energized, otherwise incomer 2, otherwise it
    is dead. The whole feeder demand is drawn from the incomer in use. No breaker, no relay.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        dead = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)
        self.forward = {f"feeder[{key}]": dead for key in ctx.keys["trains"]}
        self.reverse = {
            "incomer_1": ElectricalDemand(kw=0.0),
            "incomer_2": ElectricalDemand(kw=0.0),
        }

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        first, second = inputs.forward["incomer_1"], inputs.forward["incomer_2"]
        assert isinstance(first, ElectricalSupply) and isinstance(second, ElectricalSupply)
        live = first if first.energized else second
        if not live.energized:
            live = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)
        total = 0.0
        for key in self.ctx.keys["trains"]:
            demand = inputs.reverse[f"feeder[{key}]"]
            assert isinstance(demand, ElectricalDemand)
            total += demand.kw
            self.forward[f"feeder[{key}]"] = live
        on_first = first.energized
        on_second = second.energized and not first.energized
        self.reverse = {
            "incomer_1": ElectricalDemand(kw=total if on_first else 0.0),
            "incomer_2": ElectricalDemand(kw=total if on_second else 0.0),
        }
