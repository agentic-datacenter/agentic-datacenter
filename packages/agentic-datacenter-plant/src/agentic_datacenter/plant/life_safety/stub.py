"""Stub of `life_safety`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import ElectricalDemand, Signal
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """Fire and life safety, fidelity F0.

    Nothing ever happens: no fire, no emergency power off, no fire pump start.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        self.forward = {"fire_pump_start_request": Signal(active=False)}
        for key in ctx.keys["pods"]:
            self.forward[f"pod_fire[{key}]"] = Signal(active=False)
            self.forward[f"pod_epo[{key}]"] = Signal(active=False)
        self.reverse = {"power": ElectricalDemand(kw=0.0)}

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        pass
