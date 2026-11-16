"""Stub of `cooling.weather`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import Weather
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """Outdoor conditions, fidelity F0.

    Constant conditions.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        dry_bulb = params.get("dry_bulb_c", 20.0)
        humidity = params.get("rel_humidity_pct", 50.0)
        assert isinstance(dry_bulb, float) and isinstance(humidity, float)
        self.forward = {"ambient": Weather(dry_bulb_c=dry_bulb, rel_humidity_pct=humidity)}

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        pass
