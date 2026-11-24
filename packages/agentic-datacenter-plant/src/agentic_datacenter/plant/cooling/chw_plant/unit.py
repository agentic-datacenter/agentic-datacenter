"""The air-cooled chiller plant and its plant controller."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from agentic_datacenter.core.io import IOBoard, PointDecl, load_points
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
    Weather,
    settled,
)
from agentic_datacenter.core.state import JsonValue

from .faults import FAULTS

POINTS = load_points(Path(__file__).parent / "points.yaml")
#: The chillers of the default plant, and the number of power feeds the module has.
CHILLERS = (1, 2, 3)
FEEDS = 3
MAX_CHILLERS = 9
UNAVAILABLE = frozenset({"TRIPPED", "LOCKED_OUT"})
_CHILLER_POINT = re.compile(r"^ch\d_")
_CHILLER_3 = re.compile(r"([Cc]hiller) 3")


def plant_points(count: int) -> tuple[PointDecl, ...]:
    """Return the points of a plant of *count* chillers (ADR 0033, decision 7).

    With three, they are the points of ``points.yaml``. A fourth or later chiller
    gets points made after those of chiller 3, which starts in standby; a plant
    of fewer has no points for the chillers it lacks.
    """
    if not 1 <= count <= MAX_CHILLERS:
        raise ValueError(f"chillers must be 1 to {MAX_CHILLERS}, got {count}")
    out: list[PointDecl] = []
    for decl in POINTS:
        if decl.name.startswith("ch3_"):
            out.append(decl)
            for n in range(4, count + 1):
                out.append(
                    decl.model_copy(
                        update={
                            "name": decl.name.replace("ch3_", f"ch{n}_", 1),
                            "description": _CHILLER_3.sub(rf"\g<1> {n}", decl.description),
                        }
                    )
                )
        elif decl.name == "lead_chiller":
            lead = tuple(str(n) for n in range(1, count + 1))
            out.append(decl.model_copy(update={"values": lead}))
        else:
            out.append(decl)
    return tuple(d for d in out if not _CHILLER_POINT.match(d.name) or int(d.name[2]) <= count)


class ChwPlant(SimModule):
    """Chiller plant at fidelity F1: staging, restart lockout, a loop water node.

    The loop water has one temperature ``T`` and heat capacity ``C``::

        C dT/dt = Q_returned - Q_chillers
        Q_chillers = clip(Q_returned + C (T - setpoint) / tau, 0, capacity)

    so the chillers hold the setpoint while they have the capacity, and the
    loop warms by exactly the heat they cannot remove. Capacity falls and
    electrical input rises with ambient temperature, linearly about the design
    ambient; input at part load is ``(0.15 + 0.85 PLR)`` of full-load input.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create a plant with two chillers running and the others in standby.

        ``chillers`` (default 3) is the number of chillers. Chiller *n* is fed
        from ``power_<((n - 1) mod 3) + 1>``, so a fourth shares the first feed.
        """
        super().__init__(ctx, params)
        count = int(param_number(params, "chillers", float(len(CHILLERS))))
        self.io = IOBoard(plant_points(count))
        self.chillers = tuple(range(1, count + 1))
        self.feed_of = {n: (n - 1) % FEEDS + 1 for n in self.chillers}
        self.rated_kw = param_number(params, "chiller_kw", 1600.0)
        self.cop = param_number(params, "cop", 4.5)
        self.design_ambient_c = param_number(params, "design_ambient_c", 35.0)
        self.capacity_slope = param_number(params, "capacity_per_k", 0.012)
        self.cop_slope = param_number(params, "cop_per_k", 0.02)
        self.cop_supply_slope = param_number(params, "cop_per_k_supply", 0.025)
        self.design_supply_c = param_number(params, "design_supply_c", 18.0)
        self.loop_kj_per_k = param_number(params, "loop_kj_per_k", 83_720.0)
        self.response_s = param_number(params, "response_s", 60.0)
        self.start_s = param_number(params, "start_s", 90.0)
        self.lockout_s = param_number(params, "restart_lockout_s", 180.0)
        self.stagger_s = param_number(params, "restart_stagger_s", 20.0)
        self.up_after_s = param_number(params, "stage_up_after_s", 300.0)
        self.down_after_s = param_number(params, "stage_down_after_s", 900.0)
        self.temp = self.io.number("chws_sp_c")
        self.wanted = min(2, count)
        self.until_ms = dict.fromkeys(self.chillers, -1)
        self.above_s = self.below_s = 0.0
        self.share_kw = dict.fromkeys(self.chillers, 0.0)
        self._heat_in, self._heat_out = LazyIntegral(), LazyIntegral()
        self._settled = False

    def _state(self, n: int) -> str:
        return str(self.io[f"ch{n}_state"])

    def _set(self, n: int, state: str) -> None:
        if self._state(n) != state:
            self.io[f"ch{n}_state"] = state
            self.ctx.publish("chiller.state", {"chiller": n, "state": state})

    def _sequence(self, powered: Mapping[int, bool]) -> None:
        """Lockout after a power interruption, then start and stop to the wanted count."""
        now, io = self.ctx.now_ms, self.io
        for n in self.chillers:
            state = self._state(n)
            if not powered[n] and state != "TRIPPED":
                self._set(n, "LOCKED_OUT")
                self.until_ms[n] = -1
            elif state == "LOCKED_OUT":
                if self.until_ms[n] < 0:
                    # Staggered, so the chillers do not all return in the same second.
                    wait_s = self.lockout_s + (n - 1) * self.stagger_s
                    self.until_ms[n] = now + round(wait_s * 1000)
                elif now >= self.until_ms[n]:
                    self._set(n, "OFF")
            elif state == "STARTING" and now >= self.until_ms[n]:
                self._set(n, "RUNNING")
        if not self.ctx.controller_running():
            return  # the plant controller is down: each chiller carries on by itself
        lead = int(str(io["lead_chiller"]))
        count = len(self.chillers)
        order = [self.chillers[(lead - 1 + k) % count] for k in range(count)]
        candidates = [
            n for n in order if io.flag(f"ch{n}_enable") and self._state(n) not in UNAVAILABLE
        ]
        desired = candidates[: self.wanted]
        for n in desired:
            if self._state(n) == "OFF":
                self._set(n, "STARTING")
                self.until_ms[n] = now + round(self.start_s * 1000)
        all_running = all(self._state(n) == "RUNNING" for n in desired)
        for n in self.chillers:
            surplus = n not in desired and self._state(n) in ("RUNNING", "STARTING")
            if surplus and (all_running or not io.flag(f"ch{n}_enable")):
                self._set(n, "OFF")

    def step_slow(self, inputs: Inputs) -> None:
        """Run the plant controller and the loop for one second."""
        ambient, load = inputs.forward["ambient"], inputs.reverse["chws"]
        assert isinstance(ambient, Weather) and isinstance(load, HydronicReturn)
        powered = {}
        for n in self.chillers:
            feed = inputs.forward[f"power_{self.feed_of[n]}"]
            assert isinstance(feed, ElectricalSupply)
            powered[n] = feed.energized
        self._sequence(powered)
        io = self.io
        running = [n for n in self.chillers if self._state(n) == "RUNNING"]
        excess_k = ambient.dry_bulb_c - self.design_ambient_c
        each = self.rated_kw * min(1.3, max(0.5, 1.0 - self.capacity_slope * excess_k))
        cop = self.cop * min(1.6, max(0.5, 1.0 - self.cop_slope * excess_k))
        # Warmer chilled water means less lift: efficiency rises with supply temperature.
        lift_k = self.temp - self.design_supply_c
        cop *= min(1.3, max(0.7, 1.0 + self.cop_supply_slope * lift_k))
        capacity = each * len(running)
        pull = self.loop_kj_per_k * (self.temp - io.number("chws_sp_c")) / self.response_s
        cooling = min(capacity, max(0.0, load.heat_kw + pull))
        change = (load.heat_kw - cooling) / self.loop_kj_per_k
        self.temp += change
        plr = cooling / capacity if capacity > 0.0 else 0.0
        power_each = each / cop * (0.15 + 0.85 * plr) if running else 0.0
        self.share_kw = {n: power_each if n in running else 0.0 for n in self.chillers}
        self._heat_in.set_rate(load.heat_kw, self.ctx.now_ms)
        self._heat_out.set_rate(cooling, self.ctx.now_ms)

        # A threshold only counts while there is a chiller left to start or stop.
        up = self.ctx.controller_running()
        can_add, can_drop = up and self.wanted < len(self.chillers), up and self.wanted > 1
        high = can_add and bool(running) and 100.0 * plr > io.number("stage_up_pct")
        low = can_drop and bool(running) and 100.0 * plr < io.number("stage_down_pct")
        self.above_s = self.above_s + 1.0 if high else 0.0
        self.below_s = self.below_s + 1.0 if low else 0.0
        if self.above_s >= self.up_after_s and self.wanted < len(self.chillers):
            self.wanted, self.above_s = self.wanted + 1, 0.0
        elif self.below_s >= self.down_after_s and self.wanted > 1:
            self.wanted, self.below_s = self.wanted - 1, 0.0
        io["chws_c"], io["cooling_kw"] = self.temp, cooling
        io["power_kw"], io["plr_pct"] = power_each * len(running), 100.0 * plr
        io["capacity_kw"] = capacity
        io["load_kw"], io["unit_capacity_kw"] = max(load.heat_kw, 0.0), each
        in_transition = any(self._state(n) in ("STARTING", "LOCKED_OUT") for n in self.chillers)
        self._settled = abs(change) < 1e-9 and not (high or low or in_transition)

    def step(self, inputs: Inputs) -> None:
        """Nothing happens between the one-second steps."""

    def quiescent(self) -> bool:
        """The model advances in :meth:`step_slow` only."""
        return True

    @property
    def in_kwh(self) -> float:
        """Heat returned to the plant so far, in kWh."""
        return self._heat_in.at(self.ctx.now_ms)

    @property
    def out_kwh(self) -> float:
        """Heat removed by the chillers so far, in kWh."""
        return self._heat_out.at(self.ctx.now_ms)

    def settled(self) -> bool:
        """The plant holds its setpoint with no chiller starting, locked out or about to stage."""
        return self._settled

    def forward_outputs(self) -> Mapping[str, object]:
        """Return the water leaving the plant. Water flows whether or not a chiller runs."""
        return {"chws": HydronicSupply(available=True, supply_c=settled(self.temp))}

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the power each chiller draws from its feed."""
        demand = dict.fromkeys(range(1, FEEDS + 1), 0.0)
        for n in self.chillers:
            demand[self.feed_of[n]] += self.share_kw[n]
        return {f"power_{f}": ElectricalDemand(kw=settled(kw)) for f, kw in demand.items()}

    def heat_balance(self) -> dict[str, float]:
        """Cumulative heat returned and removed, and the heat held in the loop water, in kWh."""
        return {
            "in_kwh": self.in_kwh,
            "out_kwh": self.out_kwh,
            "stored_kwh": self.loop_kj_per_k * self.temp / 3600.0,
        }

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the faults listed in ``faults.py``."""
        if fault not in FAULTS:
            super().inject(fault, **params)
            return
        self._set(int(str(params["chiller"])), "TRIPPED" if fault == "chiller_trip" else "OFF")
        self._settled = False
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state of the plant."""
        return {
            "io": self.io.snapshot(),
            "loop": [self.temp, self.above_s, self.below_s],
            "energy": [self._heat_in.snapshot(), self._heat_out.snapshot(), self._settled],
            "wanted": self.wanted,
            "until_ms": [self.until_ms[n] for n in self.chillers],
            "share_kw": [self.share_kw[n] for n in self.chillers],
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("chiller-plant snapshot must be a mapping")
        self.io.restore(state["io"])
        loop, until, share = state["loop"], state["until_ms"], state["share_kw"]
        assert isinstance(loop, list | tuple) and isinstance(until, list | tuple)
        assert isinstance(share, list | tuple)
        self.temp, self.above_s, self.below_s = (float(str(v)) for v in loop)
        energy = state["energy"]
        assert isinstance(energy, list | tuple)
        self._heat_in.restore(energy[0])
        self._heat_out.restore(energy[1])
        self._settled = bool(energy[2])
        self.wanted = int(str(state["wanted"]))
        self.until_ms = {n: int(str(v)) for n, v in zip(self.chillers, until, strict=True)}
        self.share_kw = {n: float(str(v)) for n, v in zip(self.chillers, share, strict=True)}
