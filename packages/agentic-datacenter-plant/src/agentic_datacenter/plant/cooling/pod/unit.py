"""The air side of one POD."""

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
    Signal,
    settled,
)
from agentic_datacenter.core.state import JsonValue

from .faults import FAULTS
from .zone import ZONE_OFFSETS_K, ZoneArray

POINTS = load_points(Path(__file__).parent / "points.yaml")
AIR_CP = 1.006  # kJ/(kg K)
WATER_CP = 4.186  # kJ/(kg K)


class Pod(SimModule):
    """POD cooling at fidelity F1: three thermal nodes, a coil and a supply air loop.

    Supply-side air ``Ts`` (the IT inlet), return-side air ``Tr``, and the
    thermal mass ``Tm`` of the hall on the supply side (floor, containment,
    rack fronts), with airflow ``m`` through the IT equipment::

        Cs dTs/dt = m cp (T_in - Ts) + h (Tm - Ts)
        Cm dTm/dt = h (Ts - Tm)
        Cr dTr/dt = m cp (Ts - Tr) + Q_it + Q_fan

    With the air handlers running, ``T_in = Tr - Q_coil / (m cp)`` and
    ``Q_coil = valve * effectiveness * m cp * (Tr - T_chw)``. With them stopped
    the IT equipment recirculates its own exhaust: ``T_in = Tr``. The three
    equations sum to ``Q_it + Q_fan - Q_coil``, so energy is conserved exactly.

    With cooling lost the return side stays one IT temperature rise above the
    supply side, so the supply side warms at about ``Q / (Cs + Cm)``: the lumped
    behaviour of SDD 6.2. ``Cm`` is the calibration parameter for the 3 to 6
    minute target.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create a POD in steady state at its design load and setpoint."""
        super().__init__(ctx, params)
        self.io = IOBoard(POINTS)
        self.c_air = param_number(params, "air_node_kj_per_k", 300.0)
        self.c_mass = param_number(params, "thermal_mass_kj_per_k", 4500.0)
        self.h_mass = param_number(params, "mass_conductance_kw_per_k", 60.0)
        self.effectiveness = param_number(params, "coil_effectiveness", 0.9)
        self.fan_rated_kw = param_number(params, "fan_kw", 6.0)
        self.ahu_count = int(param_number(params, "ahu_count", 4.0))
        needed = param_number(params, "ahu_needed", 3.0)
        self.ramp_s = param_number(params, "fan_ramp_s", 30.0)
        self.design_pa = param_number(params, "design_static_pa", 50.0)
        stagger = param_number(params, "restart_stagger_s", 5.0)
        position = (
            list(ctx.keys.get("pods", ())).index(ctx.instance)
            if ctx.instance in ctx.keys.get("pods", ())
            else 0
        )
        self.restart_delay_ms = round((position % 8) * stagger * 1000)
        self.stroke_s = param_number(params, "valve_stroke_s", 60.0)
        self.kp = param_number(params, "loop_gain_per_k", 0.03)
        self.ki = param_number(params, "loop_reset_per_k_s", 0.002)
        self.critical_c = param_number(params, "critical_c", 32.0)
        self.critical_hold_s = param_number(params, "critical_hold_s", 60.0)
        self.water_rise_k = param_number(params, "water_rise_k", 8.0)
        heat = param_number(params, "design_it_kw", 150.0)
        design_airflow = param_number(params, "design_airflow_kg_s", 12.0)
        flow = design_airflow * AIR_CP
        # N+1: the needed number of units carries the design airflow at full speed.
        self.unit_airflow = design_airflow / needed
        self.speed = needed / self.ahu_count
        self.unit_kw = self.fan_rated_kw / (self.ahu_count * self.speed**3)
        self.ahu_failed = [False] * self.ahu_count
        self.powered_since_ms = -(10**9)
        self.was_powered = True
        self.on_b = False
        water = param_number(params, "design_chw_c", 18.0)
        self.ts = self.io.number("supply_air_sp_c")
        self.tr = self.ts + (heat + self.fan_rated_kw) / flow
        self.tm = self.ts
        self.valve = (heat + self.fan_rated_kw) / (self.effectiveness * flow * (self.tr - water))
        self.error = 0.0
        self.above_s = 0.0
        self.zone = ZoneArray(self.ts)
        self.measured = self.ts
        self.stuck = False
        self.heat_in, self.heat_out = LazyIntegral(), LazyIntegral()
        self._settled = False
        self._publish(coil=heat + self.fan_rated_kw, fan=self.fan_rated_kw, running=True)

    def _publish(self, coil: float, fan: float, running: bool) -> None:
        io = self.io
        io["supply_air_c"], io["return_air_c"], io["mass_c"] = self.measured, self.tr, self.tm
        io["coil_kw"], io["fan_kw"], io["fans_running"] = coil, fan, running
        io["valve_pct"] = 100.0 * self.valve

    def step_slow(self, inputs: Inputs) -> None:
        """Advance the thermal nodes and the supply air loop by one second."""
        water, heat = inputs.forward["chw"], inputs.forward["it_heat"]
        feed_a, feed_b = inputs.forward["fan_power"], inputs.forward["fan_power_b"]
        fire = inputs.forward["fire_stop"]
        assert isinstance(water, HydronicSupply) and isinstance(heat, AirHeat)
        assert isinstance(feed_a, ElectricalSupply) and isinstance(feed_b, ElectricalSupply)
        assert isinstance(fire, Signal)
        # Two supplies, like the IT load the air handlers cool: either one is enough.
        energized = feed_a.energized or feed_b.energized
        self.on_b = not feed_a.energized and feed_b.energized
        io, dt = self.io, 1.0
        now = self.ctx.now_ms
        if energized and not self.was_powered:
            self.powered_since_ms = now
        self.was_powered = energized
        # After a mains failure the air handlers come back in staggered groups (SDD 7.4).
        restarted = now - self.powered_since_ms >= self.restart_delay_ms
        units = 0
        if energized and restarted and not fire.active:
            units = self.ahu_failed.count(False)
        running = units > 0
        it_flow = heat.airflow_kg_s
        controlling = self.ctx.controller_running()

        now_s = now // 1000
        for index, offset in enumerate(ZONE_OFFSETS_K):
            reading, good = self.ctx.measure(f"zone_t{index + 1}", self.ts + offset)
            reason = self.zone.update(index, reading, good, now_s)
            if reason:
                self.ctx.publish(
                    "pod.sensor_excluded", {"sensor": f"zone_t{index + 1}", "reason": reason}
                )
            io[f"zone_t{index + 1}_c"] = reading
        mean = self.zone.mean()
        io["zone_sensors_in_mean"] = self.zone.used()
        io["zone_mean_invalid"] = mean is None
        measured = self.measured if mean is None else mean
        self.measured = measured
        moved = 0.0
        if running and controlling and not self.stuck and mean is not None:
            error = measured - io.number("supply_air_sp_c")
            move = self.kp * (error - self.error) + self.ki * error * dt
            limit = dt / self.stroke_s
            before = self.valve
            self.valve = min(1.0, max(0.0, self.valve + min(limit, max(-limit, move))))
            self.error = error
            moved = abs(self.valve - before)
        # Static pressure loop on fan speed: pressure follows the square of the
        # share of the IT airflow that the air handlers deliver.
        if not running:
            self.speed, speed_moved = 0.0, 0.0
        elif controlling:
            wanted_flow = it_flow * (io.number("static_pressure_sp_pa") / self.design_pa) ** 0.5
            target = min(1.0, wanted_flow / (units * self.unit_airflow))
            step = min(dt / self.ramp_s, max(-dt / self.ramp_s, target - self.speed))
            self.speed, speed_moved = self.speed + step, abs(step)
        else:
            speed_moved = 0.0
        ahu_flow = units * self.unit_airflow * self.speed
        share = ahu_flow / it_flow if it_flow > 0.0 else 0.0
        fan = units * self.unit_kw * self.speed**3
        through_coil, short, surplus = ahu_flow * AIR_CP, 0.0, 0.0
        if ahu_flow < it_flow:
            short = (it_flow - ahu_flow) * AIR_CP  # exhaust air recirculating to the inlets
        else:
            surplus = (ahu_flow - it_flow) * AIR_CP  # cold air bypassing the equipment
        coil = 0.0
        if running and water.available:
            coil = (
                self.valve * self.effectiveness * through_coil * max(self.tr - water.supply_c, 0.0)
            )
        off_coil = self.tr - coil / through_coil if through_coil > 0.0 else self.tr
        from_mass = self.h_mass * (self.tm - self.ts)
        d_mass = -from_mass / self.c_mass
        d_supply = (
            through_coil * (off_coil - self.ts) + short * (self.tr - self.ts) + from_mass
        ) / self.c_air
        d_return = (
            (it_flow * AIR_CP + surplus) * (self.ts - self.tr) + heat.heat_kw + fan
        ) / self.c_air
        self.tm += d_mass * dt
        self.ts += d_supply * dt
        self.tr += d_return * dt
        moved = max(moved, speed_moved)
        io["ahu_running"], io["fan_speed_pct"] = units, 100.0 * self.speed
        io["static_pressure_pa"] = self.design_pa * share * share
        self.heat_in.set_rate(heat.heat_kw + fan, now)
        self.heat_out.set_rate(coil, now)
        still = max(abs(d_mass), abs(d_supply), abs(d_return)) * dt < 1e-9 and moved < 1e-12
        quiet = self.zone.quiet() and self.ctx.measurements_static()
        waiting = energized and not restarted
        self._settled = still and self.above_s == 0.0 and quiet and not waiting

        self.above_s = self.above_s + dt if measured > self.critical_c else 0.0
        critical = self.above_s > self.critical_hold_s
        if critical != io.flag("thermally_critical"):
            self.ctx.publish(
                "pod.thermally_critical", {"active": critical, "supply_air_c": self.ts}
            )
        io["thermally_critical"] = critical
        if critical:
            io["critical_minutes"] = io.number("critical_minutes") + dt / 60.0
        self._publish(coil=coil, fan=fan, running=running)

    def step(self, inputs: Inputs) -> None:
        """Nothing happens between the one-second steps."""

    def quiescent(self) -> bool:
        """The model advances in :meth:`step_slow` only."""
        return True

    def settled(self) -> bool:
        """The model has reached steady state and will not move until an input does."""
        return self._settled

    def forward_outputs(self) -> Mapping[str, object]:
        """A POD provides no port."""
        return {}

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the water taken, the inlet temperature given back, and the fan power."""
        coil, fan = self.io.number("coil_kw"), self.io.number("fan_kw")
        return {
            "chw": HydronicReturn(settled(coil / (WATER_CP * self.water_rise_k)), settled(coil)),
            "it_heat": AirInlet(inlet_c=settled(self.ts)),
            "fan_power": ElectricalDemand(kw=0.0 if self.on_b else fan),
            "fan_power_b": ElectricalDemand(kw=fan if self.on_b else 0.0),
        }

    def heat_balance(self) -> dict[str, float]:
        """Cumulative heat in and out, and the heat held in the three nodes, in kWh."""
        stored = (self.c_air * (self.ts + self.tr) + self.c_mass * self.tm) / 3600.0
        now = self.ctx.now_ms
        return {
            "in_kwh": self.heat_in.at(now),
            "out_kwh": self.heat_out.at(now),
            "stored_kwh": stored,
        }

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the faults listed in ``faults.py``."""
        if fault not in FAULTS:
            super().inject(fault, **params)
            return
        if fault in ("ahu_fail", "ahu_restore"):
            unit = int(str(params["unit"]))
            if not 1 <= unit <= self.ahu_count:
                raise ValueError(f"{self.ctx.name}: no air handler {unit}")
            self.ahu_failed[unit - 1] = fault == "ahu_fail"
        elif fault == "sensor_reset":
            self.zone = ZoneArray(self.measured)
        elif fault in ("valve_stuck", "clear"):
            self.stuck = fault == "valve_stuck"
        else:
            self.io["leak_alarm"] = fault == "leak"
            self.ctx.publish("pod.leak", {"active": fault == "leak"})
        self._settled = False
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state of the POD."""
        return {
            "io": self.io.snapshot(),
            "nodes": [self.ts, self.tr, self.tm],
            "loop": [self.valve, self.error, self.above_s, self.stuck],
            "zone": [self.measured, self.zone.snapshot()],
            "fans": [
                self.speed,
                list(self.ahu_failed),
                self.powered_since_ms,
                self.was_powered,
                self.on_b,
            ],  # fmt: skip
            "energy": [self.heat_in.snapshot(), self.heat_out.snapshot(), self._settled],
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("POD snapshot must be a mapping")
        self.io.restore(state["io"])
        nodes, loop, energy = state["nodes"], state["loop"], state["energy"]
        assert isinstance(nodes, list | tuple) and isinstance(loop, list | tuple)
        assert isinstance(energy, list | tuple)
        self.ts, self.tr, self.tm = (float(str(v)) for v in nodes)
        self.valve, self.error, self.above_s = (float(str(v)) for v in loop[:3])
        self.stuck = bool(loop[3])
        zone = state["zone"]
        assert isinstance(zone, list | tuple)
        self.measured = float(str(zone[0]))
        self.zone.restore(zone[1])
        fans = state["fans"]
        assert isinstance(fans, list | tuple) and isinstance(fans[1], list | tuple)
        self.speed, self.ahu_failed = float(str(fans[0])), [bool(v) for v in fans[1]]
        self.powered_since_ms, self.was_powered = int(str(fans[2])), bool(fans[3])
        self.on_b = bool(fans[4])
        self.heat_in.restore(energy[0])
        self.heat_out.restore(energy[1])
        self._settled = bool(energy[2])
