"""The chilled water air conditioners of one electrical room."""

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
from agentic_datacenter.core.ports import (
    AirHeat,
    AirInlet,
    ElectricalDemand,
    ElectricalSupply,
    HydronicReturn,
    HydronicSupply,
    settled,
)
from agentic_datacenter.core.state import JsonValue

from .faults import FAULTS

POINTS = load_points(Path(__file__).parent / "points.yaml")
WATER_CP = 4.186


class Eroom(SimModule):
    """Electrical room cooling at fidelity F1: one air node on return-air control.

    ``C dT/dt = Q_ups + Q_fan - Q_coil`` with
    ``Q_coil = valve * UA * (T - T_chw)``.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create a room in steady state at its design heat and setpoint."""
        super().__init__(ctx, params)
        self.io = IOBoard(POINTS)
        self.capacity = param_number(params, "room_kj_per_k", 2000.0)
        self.ua = param_number(params, "coil_kw_per_k", 12.0)
        self.fan_rated_kw = param_number(params, "fan_kw", 4.0)
        self.stroke_s = param_number(params, "valve_stroke_s", 60.0)
        self.kp = param_number(params, "loop_gain_per_k", 0.05)
        self.ki = param_number(params, "loop_reset_per_k_s", 0.002)
        self.water_rise_k = param_number(params, "water_rise_k", 8.0)
        heat = param_number(params, "design_heat_kw", 33.0) + self.fan_rated_kw
        self.temp = self.io.number("return_air_sp_c")
        self.valve = heat / (self.ua * (self.temp - param_number(params, "design_chw_c", 18.0)))
        self.error = 0.0
        self.off = False
        trains = list(ctx.keys.get("trains", ()))
        position = trains.index(ctx.instance) if ctx.instance in trains else 0
        self.restart_delay_ms = round(
            position * param_number(params, "restart_stagger_s", 5.0) * 1000
        )
        self.powered_since_ms = -(10**9)
        self.was_powered = True
        self._heat_in, self._heat_out = LazyIntegral(), LazyIntegral()
        self._settled = False
        self.io["coil_kw"], self.io["fan_kw"] = heat, self.fan_rated_kw
        self.io["valve_pct"] = 100.0 * self.valve

    def step_slow(self, inputs: Inputs) -> None:
        """Advance the room and its control loop by one second."""
        water, heat, feed = (
            inputs.forward["chw"],
            inputs.forward["ups_heat"],
            inputs.forward["power"],
        )
        assert isinstance(water, HydronicSupply) and isinstance(heat, AirHeat)
        assert isinstance(feed, ElectricalSupply)
        io, dt = self.io, 1.0
        now = self.ctx.now_ms
        if feed.energized and not self.was_powered:
            self.powered_since_ms = now
        self.was_powered = feed.energized
        back = now - self.powered_since_ms >= self.restart_delay_ms
        running = feed.energized and back and not self.off
        moved = 0.0
        if running and self.ctx.controller_running():
            error = self.temp - io.number("return_air_sp_c")
            move = self.kp * (error - self.error) + self.ki * error * dt
            limit = dt / self.stroke_s
            before = self.valve
            self.valve = min(1.0, max(0.0, self.valve + min(limit, max(-limit, move))))
            self.error = error
            moved = abs(self.valve - before)
        coil = 0.0
        if running and water.available:
            coil = self.valve * self.ua * max(self.temp - water.supply_c, 0.0)
        fan = self.fan_rated_kw if running else 0.0
        change = (heat.heat_kw + fan - coil) * dt / self.capacity
        self.temp += change
        self._heat_in.set_rate(heat.heat_kw + fan, self.ctx.now_ms)
        self._heat_out.set_rate(coil, self.ctx.now_ms)
        waiting = feed.energized and not back
        self._settled = abs(change) < 1e-9 and moved < 1e-12 and not waiting
        io["room_c"], io["coil_kw"], io["fan_kw"] = self.temp, coil, fan
        io["valve_pct"] = 100.0 * self.valve

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
        """A room provides no port."""
        return {}

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the water taken, the room temperature given back, and the fan power."""
        coil = self.io.number("coil_kw")
        return {
            "chw": HydronicReturn(settled(coil / (WATER_CP * self.water_rise_k)), settled(coil)),
            "ups_heat": AirInlet(inlet_c=settled(self.temp)),
            "power": ElectricalDemand(kw=self.io.number("fan_kw")),
        }

    def heat_balance(self) -> dict[str, float]:
        """Cumulative heat in and out, and the heat held in the room, in kWh."""
        return {
            "in_kwh": self.in_kwh,
            "out_kwh": self.out_kwh,
            "stored_kwh": self.capacity * self.temp / 3600.0,
        }

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the faults listed in ``faults.py``."""
        if fault not in FAULTS:
            super().inject(fault, **params)
            return
        self.off = fault == "units_off"
        self._settled = False
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state of the room."""
        return {
            "io": self.io.snapshot(),
            "state": [self.temp, self.valve, self.error],
            "energy": [self._heat_in.snapshot(), self._heat_out.snapshot(), self._settled],
            "off": [self.off, self.powered_since_ms, self.was_powered],
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("electrical-room snapshot must be a mapping")
        self.io.restore(state["io"])
        values = state["state"]
        assert isinstance(values, list | tuple)
        self.temp, self.valve, self.error = (float(str(v)) for v in values)
        energy = state["energy"]
        assert isinstance(energy, list | tuple)
        self._heat_in.restore(energy[0])
        self._heat_out.restore(energy[1])
        self._settled = bool(energy[2])
        off = state["off"]
        assert isinstance(off, list | tuple)
        self.off, self.was_powered = bool(off[0]), bool(off[2])
        self.powered_since_ms = int(str(off[1]))
