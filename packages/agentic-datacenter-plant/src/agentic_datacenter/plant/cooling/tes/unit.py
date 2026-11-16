"""The chilled water thermal storage tank."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agentic_datacenter.core.io import IOBoard, load_points
from agentic_datacenter.core.module import (
    Inputs,
    LazyIntegral,
    ModuleContext,
    SimModule,
    param_number,
)
from agentic_datacenter.core.ports import HydronicReturn, HydronicSupply, settled
from agentic_datacenter.core.state import JsonValue

from .faults import INPUTS

POINTS = load_points(Path(__file__).parent / "points.yaml")
WATER_CP = 4.186


class Tes(SimModule):
    """Thermal storage at fidelity F1: a store of cooling in series with the plant.

    When the water from the plant arrives warmer than the supply setpoint, the
    tank cools it back to the setpoint from its store, for as long as charge
    remains, and returns that much less heat to the plant. When the plant has
    held its setpoint for a while, the tank recharges at a limited rate by
    asking the plant for that much more.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create a full tank."""
        super().__init__(ctx, params)
        self.io = IOBoard(POINTS)
        mass = param_number(params, "volume_m3", 45.0) * 1000.0
        rise = param_number(params, "usable_rise_k", 8.0)
        self.capacity_kwh = mass * WATER_CP * rise / 3600.0
        self.recharge_kw = param_number(params, "recharge_kw", 250.0)
        self.settle_s = param_number(params, "recharge_after_s", 60.0)
        self.band_k = param_number(params, "setpoint_band_k", 0.1)
        self.energy_kwh = self.capacity_kwh
        self.at_setpoint_s = 0.0
        self.outlet = HydronicSupply(True, self.io.number("supply_sp_c"))
        self.passed = HydronicReturn(0.0, 0.0)
        self._heat_in, self._heat_out = LazyIntegral(), LazyIntegral()
        self._settled = False

    def step_slow(self, inputs: Inputs) -> None:
        """Cover a shortfall from the store, or recharge it."""
        water, load = inputs.forward["chws_in"], inputs.reverse["chws_out"]
        assert isinstance(water, HydronicSupply) and isinstance(load, HydronicReturn)
        io, hours = self.io, 1.0 / 3600.0
        setpoint = io.number("supply_sp_c")
        excess = water.supply_c - setpoint
        shortfall = load.flow_kg_s * WATER_CP * excess if excess > 0.0 else 0.0
        discharge = recharge = 0.0
        if shortfall > 0.0 and self.energy_kwh > 0.0:
            discharge = min(shortfall, self.energy_kwh / hours)
            self.energy_kwh = max(0.0, self.energy_kwh - discharge * hours)
        # Counted only up to the settle time, so a tank at rest stops changing.
        held = min(self.settle_s, self.at_setpoint_s + 1.0)
        self.at_setpoint_s = held if excess <= self.band_k else 0.0
        room = (self.capacity_kwh - self.energy_kwh) / hours
        if discharge == 0.0 and room > 0.0 and self.at_setpoint_s >= self.settle_s:
            recharge = min(self.recharge_kw, room)
            self.energy_kwh = (
                self.capacity_kwh if recharge >= room else self.energy_kwh + recharge * hours
            )
        outlet = water.supply_c
        if discharge > 0.0:
            outlet -= discharge / (load.flow_kg_s * WATER_CP)
        self.outlet = HydronicSupply(water.available, outlet)
        self.passed = HydronicReturn(load.flow_kg_s, load.heat_kw - discharge + recharge)
        now = self.ctx.now_ms
        self._heat_in.set_rate(load.heat_kw, now)
        self._heat_out.set_rate(self.passed.heat_kw, now)
        waiting = 0.0 < self.at_setpoint_s < self.settle_s and room > 0.0
        self._settled = discharge == 0.0 and recharge == 0.0 and not waiting
        io["charge_pct"] = 100.0 * self.energy_kwh / self.capacity_kwh
        io["discharging"], io["recharging"] = discharge > 0.0, recharge > 0.0
        io["discharge_kw"], io["outlet_c"] = discharge, outlet

    def step(self, inputs: Inputs) -> None:
        """Nothing happens between the one-second steps."""

    def quiescent(self) -> bool:
        """The model advances in :meth:`step_slow` only."""
        return True

    @property
    def in_kwh(self) -> float:
        """Heat received so far, in kWh."""
        return self._heat_in.at(self.ctx.now_ms)

    @property
    def out_kwh(self) -> float:
        """Heat passed on or removed so far, in kWh."""
        return self._heat_out.at(self.ctx.now_ms)

    def settled(self) -> bool:
        """The model has reached steady state and will not move until an input does."""
        return self._settled

    def forward_outputs(self) -> Mapping[str, object]:
        """Return the water leaving the tank."""
        outlet = HydronicSupply(self.outlet.available, settled(self.outlet.supply_c))
        return {"chws_out": outlet}

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return what is passed to the plant."""
        passed = HydronicReturn(settled(self.passed.flow_kg_s), settled(self.passed.heat_kw))
        return {"chws_in": passed}

    def heat_balance(self) -> dict[str, float]:
        """Cumulative heat in and out; heat absorbed by the tank is what it has discharged."""
        return {
            "in_kwh": self.in_kwh,
            "out_kwh": self.out_kwh,
            "stored_kwh": self.capacity_kwh - self.energy_kwh,
        }

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply the scenario input listed in ``faults.py``."""
        if fault not in INPUTS:
            super().inject(fault, **params)
            return
        pct = min(100.0, max(0.0, float(str(params["pct"]))))
        self.energy_kwh = self.capacity_kwh * pct / 100.0
        self.io["charge_pct"] = pct
        self._settled = False
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state of the tank."""
        return {
            "io": self.io.snapshot(),
            "store": [self.energy_kwh, self.at_setpoint_s],
            "energy": [self._heat_in.snapshot(), self._heat_out.snapshot(), self._settled],
            "outlet": [self.outlet.available, self.outlet.supply_c],
            "passed": [self.passed.flow_kg_s, self.passed.heat_kw],
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("tank snapshot must be a mapping")
        self.io.restore(state["io"])
        store, outlet, passed = state["store"], state["outlet"], state["passed"]
        assert isinstance(store, list | tuple) and isinstance(outlet, list | tuple)
        assert isinstance(passed, list | tuple)
        self.energy_kwh, self.at_setpoint_s = (float(str(v)) for v in store)
        energy = state["energy"]
        assert isinstance(energy, list | tuple)
        self._heat_in.restore(energy[0])
        self._heat_out.restore(energy[1])
        self._settled = bool(energy[2])
        self.outlet = HydronicSupply(bool(outlet[0]), float(str(outlet[1])))
        self.passed = HydronicReturn(float(str(passed[0])), float(str(passed[1])))
