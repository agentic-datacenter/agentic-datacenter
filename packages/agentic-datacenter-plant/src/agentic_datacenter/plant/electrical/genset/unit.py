"""One standby generator set with its controller."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agentic_datacenter.core.io import IOBoard, load_points
from agentic_datacenter.core.module import Inputs, ModuleContext, SimModule
from agentic_datacenter.core.ports import (
    ElectricalDemand,
    ElectricalSupply,
    FuelDemand,
    FuelSupply,
    Signal,
)
from agentic_datacenter.core.state import JsonValue

from .faults import FAULTS
from .model import Engine, Rating

POINTS = load_points(Path(__file__).parent / "points.yaml")
DEAD = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)
RUNNING = frozenset({"READY_TO_LOAD", "LOADED", "COOLDOWN"})


def _number(params: Mapping[str, JsonValue], name: str, default: float) -> float:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"parameter {name} must be a number")
    return float(value)


class Genset(SimModule):
    """Generator at fidelity F1: start sequence, load-step response, fuel burn."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create a stopped set from the profile parameters."""
        super().__init__(ctx, params)
        self.io = IOBoard(POINTS)
        self.engine = Engine(
            Rating(
                rated_kw=_number(params, "rated_kw", 1800.0),
                fuel_l_per_h_full=_number(params, "fuel_l_per_h_full", 430.0),
                fuel_l_per_h_quarter=_number(params, "fuel_l_per_h_quarter", 130.0),
            )
        )
        self.crank_ms = round(_number(params, "crank_s", 3.0) * 1000)
        self.start_ms = round(_number(params, "start_s", 10.0) * 1000)
        self.overload_fraction = _number(params, "overload_fraction", 1.1)
        self.overload_ms = round(_number(params, "overload_s", 10.0) * 1000)
        self.since_ms = 0
        self.overload_since_ms = -1
        self.fail_next_start = False
        self.was_loaded = False

    def _go(self, state: str) -> None:
        if self.io["state"] != state:
            self.io["state"] = state
            self.since_ms = self.ctx.now_ms
            self.ctx.publish("genset.state", {"state": state})

    def step(self, inputs: Inputs) -> None:
        """Run the start sequence and the engine for one step."""
        request, fuel = inputs.forward["start_request"], inputs.forward["fuel"]
        demand = inputs.reverse["output"]
        assert isinstance(request, Signal) and isinstance(fuel, FuelSupply)
        assert isinstance(demand, ElectricalDemand)
        io, now = self.io, self.ctx.now_ms
        wanted = request.active or io.flag("test_start_request")
        state = str(io["state"])

        if state == "FAULT":
            pass
        elif not wanted:
            self._go("STOPPED")
        elif not fuel.available and state != "STOPPED":
            self._go("FAULT")
        elif state == "STOPPED":
            io["starts"] = int(io["starts"]) + 1
            self.was_loaded = False
            self._go("CRANKING")
        elif state == "CRANKING" and now - self.since_ms >= self.crank_ms:
            if self.fail_next_start or not fuel.available:
                self.fail_next_start = False
                self._go("FAULT")
            else:
                self._go("RAMPING")
        elif state == "RAMPING" and now - self.since_ms >= self.start_ms - self.crank_ms:
            self._go("READY_TO_LOAD")

        state = str(io["state"])
        running = state in RUNNING
        load = demand.kw if running else 0.0
        if running:
            self.engine.apply_load(load, self.ctx.step_ms / 1000)
            if load > 0.0:
                self.was_loaded = True
                self._go("LOADED")
            else:
                self._go("COOLDOWN" if self.was_loaded else "READY_TO_LOAD")
            limit = self.overload_fraction * self.engine.rating.rated_kw
            if load <= limit:
                self.overload_since_ms = -1
            elif self.overload_since_ms < 0:
                self.overload_since_ms = now
            elif now - self.overload_since_ms >= self.overload_ms:
                self._go("FAULT")
                running, load = False, 0.0
        if not running:
            self.engine = Engine(self.engine.rating)
            self.overload_since_ms = -1

        io["ready_to_load"] = running
        io["fault"] = io["state"] == "FAULT"
        io["load_kw"] = load
        io["frequency_pu"] = 1.0 + self.engine.frequency_dev if running else 0.0
        io["voltage_pu"] = 1.0 + self.engine.voltage_dev if running else 0.0
        io["fuel_l_per_h"] = self.engine.fuel_l_per_h() if running else 0.0

    def quiescent(self) -> bool:
        """Nothing changes while stopped or faulted, or running with no transient or timer."""
        state = self.io["state"]
        if state in ("STOPPED", "FAULT"):
            return True
        return state in RUNNING and self.engine.settled() and self.overload_since_ms < 0

    def forward_outputs(self) -> Mapping[str, object]:
        """Return the output bus state and the two hardwired signals."""
        io = self.io
        output = (
            ElectricalSupply(True, io.number("voltage_pu"), io.number("frequency_pu"))
            if io.flag("ready_to_load")
            else DEAD
        )
        return {
            "output": output,
            "ready_to_load": Signal(io.flag("ready_to_load")),
            "fault": Signal(io.flag("fault")),
        }

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the fuel drawn."""
        return {"fuel": FuelDemand(litre_per_h=self.io.number("fuel_l_per_h"))}

    def power_balance(self) -> dict[str, float]:
        """The set converts fuel to electricity; electrically it is a source with no storage."""
        load = self.io.number("load_kw")
        return {"in_kw": load, "out_kw": load, "loss_kw": 0.0, "stored_kw": 0.0}

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the faults or local actions listed in ``faults.py``."""
        if fault not in FAULTS:
            super().inject(fault, **params)
            return
        if fault == "start_failure":
            self.fail_next_start = True
        elif fault == "trip":
            self._go("FAULT")
        else:
            self._go("STOPPED")
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state of the set."""
        e = self.engine
        return {
            "io": self.io.snapshot(),
            "engine": [e.load_kw, e.frequency_dev, e.voltage_dev],
            "timers": [self.since_ms, self.overload_since_ms],
            "flags": [self.fail_next_start, self.was_loaded],
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("generator snapshot must be a mapping")
        self.io.restore(state["io"])
        engine, timers, flags = state["engine"], state["timers"], state["flags"]
        assert isinstance(engine, list | tuple) and isinstance(timers, list | tuple)
        assert isinstance(flags, list | tuple)
        e = self.engine
        e.load_kw, e.frequency_dev, e.voltage_dev = (float(v) for v in engine)
        self.since_ms, self.overload_since_ms = int(timers[0]), int(timers[1])
        self.fail_next_start, self.was_loaded = bool(flags[0]), bool(flags[1])
