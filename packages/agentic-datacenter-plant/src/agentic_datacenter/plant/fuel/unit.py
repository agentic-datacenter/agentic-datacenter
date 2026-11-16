"""The fuel oil system: bulk storage, transfer pumps, sub-base tanks, polishing."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from agentic_datacenter.core.io import IOBoard, PointDecl, load_points
from agentic_datacenter.core.module import Inputs, ModuleContext, SimModule, param_number
from agentic_datacenter.core.ports import ElectricalDemand, ElectricalSupply, FuelDemand, FuelSupply
from agentic_datacenter.core.state import JsonValue

from .faults import FAULTS, INPUTS

TEMPLATE = load_points(Path(__file__).parent / "points.yaml")
NOT_FALLING_H = 1000.0


def point_key(key: str) -> str:
    """Return *key* in the form it takes inside a point name."""
    return re.sub(r"[^a-z0-9]", "_", key.lower())


def expand_points(trains: tuple[str, ...]) -> tuple[PointDecl, ...]:
    """Return the point list for *trains*: every sub_ point once per generator."""
    out: list[PointDecl] = []
    for decl in TEMPLATE:
        if "sub_" not in decl.name:
            out.append(decl)
            continue
        for train in trains:
            name = decl.name.replace("sub_", f"sub_{point_key(train)}_", 1)
            text = f"{decl.description} (generator {train})"
            out.append(decl.model_copy(update={"name": name, "description": text}))
    return tuple(out)


class Fuel(SimModule):
    """Fuel oil at fidelity F1: a mass balance per tank and level-switch refill.

    Each generator draws from its own sub-base tank. A transfer pump refills
    the tank from bulk storage: it starts at the low switch and stops at the
    high switch. The pumps and the polishing skid need power and stop on an
    interstitial leak. An independent high-high switch trips a pump that did
    not stop. Polishing circulates bulk fuel on a schedule and moves no fuel
    out of the tank.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create full bulk storage and sub-base tanks at their high switch."""
        super().__init__(ctx, params)
        self.trains = tuple(ctx.keys["trains"])
        self.io = IOBoard(expand_points(self.trains))
        self.bulk_capacity_l = param_number(params, "bulk_tank_m3", 25.0) * 1000.0 * 2
        self.sub_capacity_l = param_number(params, "sub_base_tank_l", 4000.0)
        self.low_pct = param_number(params, "low_switch_pct", 50.0)
        self.high_pct = param_number(params, "high_switch_pct", 90.0)
        self.alarm_pct = param_number(params, "low_alarm_pct", 25.0)
        self.high_high_pct = param_number(params, "high_high_switch_pct", 98.0)
        self.transfer_l_per_h = param_number(params, "transfer_l_per_h", 1500.0)
        self.pump_kw = param_number(params, "transfer_pump_kw", 1.5)
        self.polish_kw = param_number(params, "polishing_kw", 2.2)
        self.polish_every_s = param_number(params, "polish_every_h", 168.0) * 3600.0
        self.polish_for_s = param_number(params, "polish_for_h", 4.0) * 3600.0
        self.bulk_l = self.bulk_capacity_l
        self.sub_l = {t: self.sub_capacity_l * self.high_pct / 100.0 for t in self.trains}
        self.filling = dict.fromkeys(self.trains, False)
        self.pump_failed = dict.fromkeys(self.trains, False)
        self.stuck: dict[str, str] = dict.fromkeys(self.trains, "")
        self.tripped = dict.fromkeys(self.trains, False)
        self.leak = "NONE"
        self.power_kw = 0.0
        self._settled = False

    # -- the one-second model ------------------------------------------------------------

    def _wants_fuel(self, train: str, pct: float) -> bool:
        """The level controller of one sub-base tank, as its switches report."""
        stuck = self.stuck[train]
        low = stuck == "dry" or (stuck != "wet" and pct <= self.low_pct)
        high = stuck == "wet" or (stuck != "dry" and pct >= self.high_pct)
        if high:
            self.filling[train] = False
        elif low:
            self.filling[train] = True
        return self.filling[train]

    def step_slow(self, inputs: Inputs) -> None:
        """Burn, refill and polish for one second."""
        feed = inputs.forward["power"]
        assert isinstance(feed, ElectricalSupply)
        io, hours = self.io, 1.0 / 3600.0
        powered = feed.energized and io.flag("transfer_enable") and self.leak == "NONE"
        power = 0.0
        moving = False
        for train in self.trains:
            key = point_key(train)
            demand = inputs.reverse[f"supply[{train}]"]
            burn = demand.litre_per_h if isinstance(demand, FuelDemand) else 0.0
            level = max(0.0, self.sub_l[train] - burn * hours)
            pct = 100.0 * level / self.sub_capacity_l
            if pct >= self.high_high_pct and self.filling[train]:
                self.tripped[train] = True
            elif pct < self.high_pct:
                self.tripped[train] = False
            called = self._wants_fuel(train, pct) and not self.tripped[train]
            running = called and powered and not self.pump_failed[train] and self.bulk_l > 0.0
            inflow = 0.0
            if running:
                room = self.sub_capacity_l - level
                inflow = min(self.transfer_l_per_h * hours, room, self.bulk_l)
                level += inflow
                self.bulk_l -= inflow
                power += self.pump_kw
            self.sub_l[train] = level
            net = burn - inflow / hours
            io[f"sub_{key}_level_pct"] = 100.0 * level / self.sub_capacity_l
            io[f"sub_{key}_time_to_empty_h"] = (
                min(NOT_FALLING_H, level / net) if net > 1e-9 else NOT_FALLING_H
            )
            io[f"sub_{key}_pump_running"] = running
            io[f"alarm_sub_{key}_pump_fault"] = (
                called and feed.energized and self.pump_failed[train]
            )
            io[f"alarm_sub_{key}_low_level"] = 100.0 * level / self.sub_capacity_l < self.alarm_pct
            io[f"alarm_sub_{key}_overfill"] = self.tripped[train]
            moving = moving or burn > 0.0 or running
        now_s = self.ctx.now_ms / 1000.0
        due = now_s >= self.polish_every_s and now_s % self.polish_every_s < self.polish_for_s
        polishing = due and feed.energized and io.flag("polish_enable") and self.leak == "NONE"
        if polishing:
            power += self.polish_kw
        io["polishing"] = polishing
        io["bulk_litre"] = self.bulk_l
        io["bulk_level_pct"] = 100.0 * self.bulk_l / self.bulk_capacity_l
        io["alarm_leak"], io["leak_location"] = self.leak != "NONE", self.leak
        io["power_kw"] = self.power_kw = power
        self._settled = not moving

    def step(self, inputs: Inputs) -> None:
        """Nothing happens between the one-second steps."""

    def quiescent(self) -> bool:
        """The model advances in :meth:`step_slow` only."""
        return True

    def _polish_near(self) -> bool:
        """Scheduled polishing is running, about to start or has just stopped."""
        now_s = self.ctx.now_ms / 1000.0
        phase = now_s % self.polish_every_s
        starting = phase >= self.polish_every_s - 5.0
        running = now_s >= self.polish_every_s and phase < self.polish_for_s + 5.0
        return starting or running

    def settled(self) -> bool:
        """Nothing burns, no pump runs and the polishing schedule is not due."""
        return self._settled and not self._polish_near()

    def forward_outputs(self) -> Mapping[str, object]:
        """Return, per generator, whether its sub-base tank has fuel."""
        return {f"supply[{t}]": FuelSupply(available=self.sub_l[t] > 0.0) for t in self.trains}

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the power the pumps and the polishing skid draw."""
        return {"power": ElectricalDemand(kw=self.power_kw)}

    def total_litre(self) -> float:
        """Return all the fuel in the system, for the mass balance."""
        return self.bulk_l + sum(self.sub_l.values())

    # -- faults ---------------------------------------------------------------------------

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the faults or scenario inputs listed in ``faults.py``."""
        if fault not in FAULTS and fault not in INPUTS:
            super().inject(fault, **params)
            return
        train = str(params.get("train", ""))
        if fault in ("interstitial_leak", "leak_clear"):
            location = str(params.get("location", "BULK"))
            if fault == "interstitial_leak" and location not in ("BULK", "SUB_BASE"):
                raise ValueError("location must be BULK or SUB_BASE")
            self.leak = location if fault == "interstitial_leak" else "NONE"
        elif fault == "set_bulk":
            pct = min(100.0, max(0.0, float(str(params["pct"]))))
            self.bulk_l = self.bulk_capacity_l * pct / 100.0
        elif train not in self.trains:
            raise ValueError(f"train must be one of {list(self.trains)}, not {train!r}")
        elif fault == "set_level":
            pct = min(100.0, max(0.0, float(str(params["pct"]))))
            self.sub_l[train] = self.sub_capacity_l * pct / 100.0
        elif fault in ("transfer_pump_failure", "transfer_pump_restore"):
            self.pump_failed[train] = fault == "transfer_pump_failure"
        elif fault == "stuck_level_switch":
            state = str(params.get("state", "wet"))
            if state not in ("wet", "dry"):
                raise ValueError("state must be wet or dry")
            self.stuck[train] = state
        else:
            self.stuck[train] = ""
        self._settled = False
        self.ctx.wake()

    # -- state ----------------------------------------------------------------------------

    def snapshot(self) -> JsonValue:
        """Return the complete state of the fuel system."""
        return {
            "io": self.io.snapshot(),
            "bulk_l": self.bulk_l,
            "sub_l": dict(self.sub_l),
            "filling": dict(self.filling),
            "pump_failed": dict(self.pump_failed),
            "stuck": dict(self.stuck),
            "tripped": dict(self.tripped),
            "leak": self.leak,
            "power_kw": self.power_kw,
            "settled": self._settled,
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("fuel snapshot must be a mapping")
        self.io.restore(state["io"])
        self.bulk_l = float(str(state["bulk_l"]))
        tables = {k: state[k] for k in ("sub_l", "filling", "pump_failed", "stuck", "tripped")}
        if not all(isinstance(t, Mapping) for t in tables.values()):
            raise ValueError("fuel snapshot is malformed")
        self.sub_l = {k: float(str(v)) for k, v in tables["sub_l"].items()}  # type: ignore[union-attr]
        self.filling = {k: bool(v) for k, v in tables["filling"].items()}  # type: ignore[union-attr]
        self.pump_failed = {k: bool(v) for k, v in tables["pump_failed"].items()}  # type: ignore[union-attr]
        self.stuck = {k: str(v) for k, v in tables["stuck"].items()}  # type: ignore[union-attr]
        self.tripped = {k: bool(v) for k, v in tables["tripped"].items()}  # type: ignore[union-attr]
        self.leak = str(state["leak"])
        self.power_kw = float(str(state["power_kw"]))
        self._settled = bool(state["settled"])
