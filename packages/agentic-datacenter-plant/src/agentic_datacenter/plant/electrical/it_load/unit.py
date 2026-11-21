"""The IT equipment of one POD."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path

from agentic_datacenter.core.io import IOBoard, load_points
from agentic_datacenter.core.module import Inputs, ModuleContext, SimModule, param_number
from agentic_datacenter.core.ports import (
    AirHeat,
    AirInlet,
    ElectricalDemand,
    ElectricalSupply,
    Signal,
)
from agentic_datacenter.core.state import JsonValue

from .faults import INPUTS

POINTS = load_points(Path(__file__).parent / "points.yaml")
FEEDS = ("feed_a", "feed_b")


TRACES = ("steady", "diurnal", "accelerated")
DAY_MS = 86_400_000


class ItLoad(SimModule):
    """IT load at fidelity F1 on the electrical side: two feeds, input range, energy lost.

    A feed is usable when it is energized and inside the steady-state input
    range of the equipment (plus or minus 10 % of nominal, the ITI curve as
    tabulated in secondary sources, SDD 6.6). The load is shared evenly by the
    usable feeds. Fans and workload
    follow below.

    Server fans run at a speed that rises with inlet temperature above a
    reference, and draw power with the cube of that speed, so a warmer supply
    air setpoint has a cost (ADC-FID-003). The workload follows one of three
    traces: steady, diurnal, or accelerated-compute with large fast swings.

    The servers protect themselves from hot inlet air. When the inlet has been
    above the shutdown temperature for the hold time, the load of the POD
    trips: nothing is drawn and the energy the workload asks for is counted as
    lost. It starts again only when the inlet has been at or below the restart
    temperature for the restart hold time.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create the load of one POD at its design value."""
        super().__init__(ctx, params)
        self.io = IOBoard(POINTS)
        self.design_kw = param_number(params, "design_kw", 150.0)
        self.airflow = param_number(params, "airflow_kg_s", 12.0)
        self.low_pu = param_number(params, "input_low_pu", 0.9)
        self.high_pu = param_number(params, "input_high_pu", 1.1)
        self.fraction = 1.0
        self.fan_fraction = param_number(params, "fan_fraction", 0.03)
        self.fan_ref_c = param_number(params, "fan_reference_c", 25.0)
        self.fan_slope = param_number(params, "fan_speed_per_k", 0.06)
        self.fan_max_speed = param_number(params, "fan_max_speed", 2.5)
        self.trace = str(params.get("trace", "steady"))
        if self.trace not in TRACES:
            raise ValueError(f"{ctx.name}: unknown workload trace {self.trace!r}")
        self.shutdown_c = param_number(params, "shutdown_inlet_c", 40.0)
        self.shutdown_ms = round(param_number(params, "shutdown_hold_s", 60.0) * 1000)
        self.restart_c = param_number(params, "restart_inlet_c", 32.0)
        self.restart_ms = round(param_number(params, "restart_hold_s", 300.0) * 1000)
        self.next_change_ms = 0
        self.fan_speed = 1.0
        self.tripped = False
        self.since_ms: int | None = None
        self._share = dict.fromkeys(FEEDS, 0.0)

    def step(self, inputs: Inputs) -> None:
        """Draw the workload from the usable feeds and count what cannot be drawn."""
        epo, inlet = inputs.forward["epo"], inputs.reverse["heat"]
        assert isinstance(epo, Signal)
        usable = []
        for name in FEEDS:
            feed = inputs.forward[name]
            assert isinstance(feed, ElectricalSupply)
            if feed.energized and self.low_pu <= feed.voltage_pu <= self.high_pu:
                usable.append(name)
        io = self.io
        if isinstance(inlet, AirInlet):
            # The reading saturates at the end of the sensor's range; the air may be hotter.
            io["inlet_c"] = min(120.0, max(-40.0, inlet.inlet_c))
        # Server fans speed up with inlet temperature; their power follows the cube of speed.
        warm = max(0.0, io.number("inlet_c") - self.fan_ref_c)
        self.fan_speed = min(self.fan_max_speed, 1.0 + self.fan_slope * warm)
        fan = self.design_kw * self.fan_fraction * self.fan_speed**3
        workload = self.design_kw * (1.0 - self.fan_fraction) * self.fraction
        wanted = 0.0 if epo.active else workload + fan
        served = wanted if usable and not self.tripped else 0.0
        self._share = {n: served / len(usable) if n in usable else 0.0 for n in FEEDS}
        dropped = wanted > 0.0 and not usable
        if wanted > 0.0 and served == 0.0:
            io["kwh_lost"] = io.number("kwh_lost") + wanted * self.ctx.step_ms / 3_600_000
        io["demand_kw"], io["served_kw"], io["dropped"] = wanted, served, dropped
        io["fan_kw"] = fan if served > 0.0 else 0.0
        io["workload_pct"] = 100.0 * self.fraction
        io["airflow_kg_s"] = self.airflow * self.fan_speed

    def step_slow(self, inputs: Inputs) -> None:
        """Watch the inlet temperature and move along the workload trace."""
        now = self.ctx.now_ms
        inlet = inputs.reverse["heat"]
        if isinstance(inlet, AirInlet):
            self._protect(inlet.inlet_c, now)
        if self.trace == "diurnal":
            wave = math.sin(2.0 * math.pi * (now / DAY_MS - 8.0 / 24.0))
            self.fraction = 0.75 + 0.25 * wave
        elif self.trace == "accelerated" and now >= self.next_change_ms:
            stream = self.ctx.rng("trace")
            self.fraction = stream.uniform(0.4, 1.0)
            self.next_change_ms = now + round(stream.uniform(30.0, 300.0) * 1000)

    def _protect(self, inlet_c: float, now: int) -> None:
        """Trip the load on a hot inlet, and start it again once the inlet is cool."""
        if self.tripped:
            counting, hold = inlet_c <= self.restart_c, self.restart_ms
        else:
            counting, hold = inlet_c > self.shutdown_c, self.shutdown_ms
        if not counting:
            self.since_ms = None
            return
        if self.since_ms is None:
            self.since_ms = now
        if now - self.since_ms >= hold:
            self.tripped, self.since_ms = not self.tripped, None
            self.io["thermal_trip"] = self.tripped
            self.ctx.publish("it_load.thermal_trip", {"active": self.tripped, "inlet_c": inlet_c})

    def settled(self) -> bool:
        """A steady workload does not need the one-second step while the protection is idle."""
        return self.trace == "steady" and not self.tripped and self.since_ms is None

    def quiescent(self) -> bool:
        """Nothing changes unless energy is being lost."""
        return not (self.io.flag("dropped") or self.tripped)

    def forward_outputs(self) -> Mapping[str, object]:
        """Return the heat released: all the power served."""
        airflow = self.airflow * self.fan_speed
        return {"heat": AirHeat(heat_kw=self.io.number("served_kw"), airflow_kg_s=airflow)}

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the power drawn from each feed."""
        return {name: ElectricalDemand(kw=self._share[name]) for name in FEEDS}

    def power_balance(self) -> dict[str, float]:
        """Everything drawn is released as heat."""
        served = self.io.number("served_kw")
        return {"in_kw": served, "out_kw": 0.0, "loss_kw": served, "stored_kw": 0.0}

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the scenario inputs listed in ``faults.py``."""
        if fault not in INPUTS:
            super().inject(fault, **params)
            return
        self.fraction = min(max(float(params["fraction"]), 0.0), 2.0)  # type: ignore[arg-type]
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state of the load."""
        return {
            "io": self.io.snapshot(),
            "fraction": [self.fraction, self.fan_speed, self.next_change_ms],
            "share": [self._share[n] for n in FEEDS],
            "protection": [self.tripped, self.since_ms],
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("IT-load snapshot must be a mapping")
        self.io.restore(state["io"])
        share = state["share"]
        assert isinstance(share, list | tuple)
        fraction = state["fraction"]
        assert isinstance(fraction, list | tuple)
        self.fraction, self.fan_speed = float(str(fraction[0])), float(str(fraction[1]))
        self.next_change_ms = int(str(fraction[2]))
        self._share = {n: float(v) for n, v in zip(FEEDS, share, strict=True)}
        protection = state["protection"]
        assert isinstance(protection, list | tuple)
        self.tripped = bool(protection[0])
        self.since_ms = None if protection[1] is None else int(str(protection[1]))
