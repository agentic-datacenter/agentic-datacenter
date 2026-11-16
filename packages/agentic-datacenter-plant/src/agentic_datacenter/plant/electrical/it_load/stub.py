"""Stub of `electrical.it_load`: fixed, documented behaviour with the module's ports."""

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, LatchedModule, ModuleContext
from agentic_datacenter.core.ports import AirHeat, ElectricalDemand, ElectricalSupply, Signal
from agentic_datacenter.core.state import JsonValue


class Stub(LatchedModule):
    """IT load of one POD, fidelity F0.

    Draws the design load, split evenly over the feeds that are energized, and all of it
    from one feed when the other is dead. Draws nothing when both are dead or emergency
    power off is active. All power drawn is released as heat at a fixed airflow.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Set the fixed outputs."""
        super().__init__(ctx, params)
        design_kw = params.get("design_kw", 150.0)
        airflow = params.get("airflow_kg_s", 12.0)
        assert isinstance(design_kw, float) and isinstance(airflow, float)
        self._design_kw, self._airflow = design_kw, airflow
        self.forward = {"heat": AirHeat(heat_kw=0.0, airflow_kg_s=airflow)}
        self.reverse = {"feed_a": ElectricalDemand(kw=0.0), "feed_b": ElectricalDemand(kw=0.0)}

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        feed_a, feed_b, epo = (
            inputs.forward["feed_a"],
            inputs.forward["feed_b"],
            inputs.forward["epo"],
        )
        assert isinstance(feed_a, ElectricalSupply) and isinstance(feed_b, ElectricalSupply)
        assert isinstance(epo, Signal)
        live = (
            []
            if epo.active
            else [n for n, f in (("feed_a", feed_a), ("feed_b", feed_b)) if f.energized]
        )
        share = self._design_kw / len(live) if live else 0.0
        self.reverse = {
            name: ElectricalDemand(kw=share if name in live else 0.0)
            for name in ("feed_a", "feed_b")
        }
        self.forward["heat"] = AirHeat(heat_kw=share * len(live), airflow_kg_s=self._airflow)
