"""The packaged chilled water pump station."""

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
    ElectricalDemand,
    ElectricalSupply,
    HydronicReturn,
    HydronicSupply,
    settled,
)
from agentic_datacenter.core.state import JsonValue

from .faults import FAULTS

POINTS = load_points(Path(__file__).parent / "points.yaml")
PUMPS = (1, 2, 3)


class PumpStation(SimModule):
    """Pump station at fidelity F1: two duty pumps and a standby on variable speed.

    Speed is the highest of the speed the flow asks for, the speed the
    differential pressure setpoint asks for (head follows the square of speed)
    and a minimum; electrical power follows the cube of speed (affinity laws).
    Pump power ends up as heat in the water. When the running pumps cannot
    deliver the flow asked for, the loop is short of cooling in proportion, and
    that is passed on as a warmer supply temperature.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create a station with pumps 1 and 2 on duty."""
        super().__init__(ctx, params)
        self.io = IOBoard(POINTS)
        self.rated_flow = param_number(params, "pump_flow_kg_s", 45.0)
        self.rated_kw = param_number(params, "pump_kw", 30.0)
        self.rated_dp = param_number(params, "rated_dp_kpa", 200.0)
        self.min_speed = param_number(params, "min_speed", 0.3)
        self.duty = int(param_number(params, "duty_pumps", 2.0))
        self.lag_s = param_number(params, "transport_lag_s", 30.0)
        self.water_rise_k = param_number(params, "water_rise_k", 8.0)
        self.failed = dict.fromkeys(PUMPS, False)
        self.stagger_s = param_number(params, "restart_stagger_s", 5.0)
        self.powered_since_ms = dict.fromkeys(PUMPS, -(10**9))
        self.was_powered = dict.fromkeys(PUMPS, True)
        self.selected: list[int] = [1, 2]
        self.supply_c = self.io.number("supply_c")
        self.available = True
        self.share_kw = dict.fromkeys(PUMPS, 0.0)
        self.passed = HydronicReturn(0.0, 0.0)
        self._heat_in, self._heat_out = LazyIntegral(), LazyIntegral()
        self._pump_heat = LazyIntegral()
        self._settled = False

    def step_slow(self, inputs: Inputs) -> None:
        """Choose the running pumps, their speed, and what reaches the loop."""
        water, load = inputs.forward["chws_in"], inputs.reverse["chw"]
        assert isinstance(water, HydronicSupply) and isinstance(load, HydronicReturn)
        io = self.io
        lead = int(str(io["lead_pump"]))
        order = [PUMPS[(lead - 1 + k) % 3] for k in range(3)]
        now = self.ctx.now_ms
        usable = []
        for n in order:
            feed = inputs.forward[f"power_{n}"]
            assert isinstance(feed, ElectricalSupply)
            if feed.energized and not self.was_powered[n]:
                self.powered_since_ms[n] = now
            self.was_powered[n] = feed.energized
            # After a mains failure pump n waits n stagger periods (SDD 7.4).
            back = now - self.powered_since_ms[n] >= round(n * self.stagger_s * 1000)
            if feed.energized and back and not self.failed[n]:
                usable.append(n)
        if self.ctx.controller_running():
            self.selected = usable[: self.duty]
        # With the controller down the selection stands; a pump that cannot run just stops.
        running = [n for n in self.selected if n in usable]
        capacity = len(running) * self.rated_flow
        self.available = water.available and bool(running)
        if self.available:
            by_flow = load.flow_kg_s / capacity
            by_head = (io.number("dp_sp_kpa") / self.rated_dp) ** 0.5
            speed = min(1.0, max(self.min_speed, by_flow, by_head))
            delivered = min(1.0, capacity / load.flow_kg_s) if load.flow_kg_s > 0.0 else 1.0
            each = self.rated_kw * speed**3
            target = water.supply_c + (1.0 - delivered) * self.water_rise_k
            change = (target - self.supply_c) / self.lag_s
            self.supply_c += change
            self.passed = HydronicReturn(
                load.flow_kg_s * delivered, load.heat_kw + each * len(running)
            )
        else:
            speed, each, change = 0.0, 0.0, 0.0
            self.passed = HydronicReturn(0.0, 0.0)
        self.share_kw = {n: each if n in running and self.available else 0.0 for n in PUMPS}
        power = sum(self.share_kw.values())
        now = self.ctx.now_ms
        self._heat_in.set_rate(load.heat_kw + power if self.available else 0.0, now)
        self._heat_out.set_rate(self.passed.heat_kw, now)
        self._pump_heat.set_rate(power, now)
        # A pump still waiting out its restart delay will change things by itself.
        waiting = any(self.was_powered[n] and not self.failed[n] and n not in usable for n in PUMPS)
        self._settled = abs(change) < 1e-9 and not waiting
        for n in PUMPS:
            io[f"p{n}_running"] = self.share_kw[n] > 0.0
        io["speed_pct"], io["power_kw"] = 100.0 * speed, power
        io["flow_kg_s"], io["supply_c"] = self.passed.flow_kg_s, self.supply_c

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
        """Return the chilled water offered to the consumers."""
        return {"chw": HydronicSupply(available=self.available, supply_c=settled(self.supply_c))}

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return what is passed upstream and the power each pump draws."""
        passed = HydronicReturn(settled(self.passed.flow_kg_s), settled(self.passed.heat_kw))
        out: dict[str, object] = {"chws_in": passed}
        out.update({f"power_{n}": ElectricalDemand(kw=settled(self.share_kw[n])) for n in PUMPS})
        return out

    def heat_balance(self) -> dict[str, float]:
        """Cumulative heat in (load plus pump power) and out; the station stores none."""
        return {"in_kwh": self.in_kwh, "out_kwh": self.out_kwh, "stored_kwh": 0.0}

    def pump_heat_kwh(self) -> float:
        """Pump power added to the water so far, in kWh."""
        return self._pump_heat.at(self.ctx.now_ms)

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the faults listed in ``faults.py``."""
        if fault not in FAULTS:
            super().inject(fault, **params)
            return
        self.failed[int(str(params["pump"]))] = fault == "pump_fail"
        self._settled = False
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state of the station."""
        return {
            "io": self.io.snapshot(),
            "failed": [self.failed[n] for n in PUMPS],
            "restart": [
                list(self.selected),
                [self.powered_since_ms[n] for n in PUMPS],
                [self.was_powered[n] for n in PUMPS],
            ],
            "share_kw": [self.share_kw[n] for n in PUMPS],
            "water": [self.supply_c, self.available, self.passed.flow_kg_s, self.passed.heat_kw],
            "energy": [
                self._heat_in.snapshot(),
                self._heat_out.snapshot(),
                self._settled,
                self._pump_heat.snapshot(),
            ],
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("pump-station snapshot must be a mapping")
        self.io.restore(state["io"])
        failed, share = state["failed"], state["share_kw"]
        water, energy = state["water"], state["energy"]
        assert isinstance(failed, list | tuple) and isinstance(share, list | tuple)
        assert isinstance(water, list | tuple) and isinstance(energy, list | tuple)
        self.failed = {n: bool(v) for n, v in zip(PUMPS, failed, strict=True)}
        restart = state["restart"]
        assert isinstance(restart, list | tuple)
        selected, since, powered = restart
        assert isinstance(selected, list | tuple) and isinstance(since, list | tuple)
        assert isinstance(powered, list | tuple)
        self.selected = [int(str(n)) for n in selected]
        self.powered_since_ms = {n: int(str(v)) for n, v in zip(PUMPS, since, strict=True)}
        self.was_powered = {n: bool(v) for n, v in zip(PUMPS, powered, strict=True)}
        self.share_kw = {n: float(str(v)) for n, v in zip(PUMPS, share, strict=True)}
        self.supply_c, self.available = float(str(water[0])), bool(water[1])
        self.passed = HydronicReturn(float(str(water[2])), float(str(water[3])))
        self._heat_in.restore(energy[0])
        self._heat_out.restore(energy[1])
        self._settled = bool(energy[2])
        self._pump_heat.restore(energy[3])
