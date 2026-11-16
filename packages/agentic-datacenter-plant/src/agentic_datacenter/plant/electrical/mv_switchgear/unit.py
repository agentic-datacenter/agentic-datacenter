"""The 36 kV switchboard: two incomers, one feeder per train, and their relays."""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from pathlib import Path

import yaml

from agentic_datacenter.core.io import IOBoard, PointDecl, parse_points
from agentic_datacenter.core.module import Inputs, ModuleContext, ModuleContractError, SimModule
from agentic_datacenter.core.ports import ElectricalDemand, ElectricalSupply
from agentic_datacenter.core.state import JsonValue

from .faults import ACTIONS, REMOTE_SERVICES
from .model import ProtectedBreaker

TEMPLATES = yaml.safe_load((Path(__file__).parent / "points.yaml").read_text(encoding="utf-8"))
DEAD = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)
INCOMERS = ("inc_1", "inc_2")
BUS_ELEMENTS = (
    ("bus_undervoltage", "bus_v_pu", "low_pu", -1),
    ("bus_overvoltage", "bus_v_pu", "high_pu", 1),
    ("bus_underfrequency", "bus_f_pu", "low_pu", -1),
    ("bus_overfrequency", "bus_f_pu", "high_pu", 1),
)


def _number(params: Mapping[str, JsonValue], name: str, default: float) -> float:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"parameter {name} must be a number")
    return float(value)


def _points(feeders: Mapping[str, str]) -> tuple[PointDecl, ...]:
    """Expand the point templates for the incomers and for this instance's feeders."""
    kinds = {**dict.fromkeys(INCOMERS, "incomer"), **dict.fromkeys(feeders.values(), "feeder")}
    out = []
    for template in TEMPLATES:
        entry = dict(template)
        scope = entry.pop("for")
        if scope == "bus":
            out.append(entry)
            continue
        for breaker, kind in kinds.items():
            if scope in ("any", kind):
                out.append({**entry, "name": entry["name"].format(b=breaker)})
    return parse_points(out)


class MvSwitchgear(SimModule):
    """MV switchboard at fidelity F1: bus, breakers and protection elements (SDD 8.5).

    Phase current is derived from real power at nominal voltage and an assumed
    power factor; a scenario can add a fault current at any node. Tripping is
    local to each relay and tier T0.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create a switchboard with every breaker closed."""
        super().__init__(ctx, params)
        self.feeders = {
            key: "fdr_" + re.sub(r"[^a-z0-9]", "_", key.lower()) for key in ctx.keys["trains"]
        }
        self.io = IOBoard(_points(self.feeders))
        self.breakers = {name: ProtectedBreaker() for name in (*INCOMERS, *self.feeders.values())}
        kv = _number(params, "nominal_kv", 36.0)
        self.kw_per_amp = math.sqrt(3.0) * kv * _number(params, "power_factor", 0.95)
        self.low_pu = _number(params, "bus_low_pu", 0.9)
        self.high_pu = _number(params, "bus_high_pu", 1.1)
        self.instantaneous_ms = _number(params, "instantaneous_ms", 20.0)
        self.breaker_ms = _number(params, "breaker_ms", 50.0)
        # The plant starts in normal operation, not from a dead bus.
        self.bus = ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0)
        self.bus_since_ms = dict.fromkeys((e[0] for e in BUS_ELEMENTS), -1)
        self._incomer_kw = dict.fromkeys(INCOMERS, 0.0)
        self._served_kw = 0.0
        self._changed = True

    def _node(self, node: object) -> str:
        text = str(node)
        if text in ("incomer_1", "incomer_2"):
            return "inc_" + text[-1]
        match = re.fullmatch(r"feeder\[(.+)\]", text)
        if match and match.group(1) in self.feeders:
            return self.feeders[match.group(1)]
        raise ModuleContractError(f"{self.ctx.name}: no node {text!r}")

    def step(self, inputs: Inputs) -> None:
        """Open tripped breakers, energize the bus, run every relay."""
        now, io, before = self.ctx.now_ms, self.io, self.snapshot()
        for breaker in self.breakers.values():
            breaker.part_contacts(now)
        supplies = {}
        for name, port in zip(INCOMERS, ("incomer_1", "incomer_2"), strict=True):
            supply = inputs.forward[port]
            assert isinstance(supply, ElectricalSupply)
            supplies[name] = supply
        in_service = [n for n in INCOMERS if self.breakers[n].closed and supplies[n].energized]
        self.bus = supplies[in_service[0]] if in_service else DEAD
        io["bus_v_pu"], io["bus_f_pu"] = self.bus.voltage_pu, self.bus.frequency_pu

        served = fault_total = 0.0
        for key, name in self.feeders.items():
            breaker, demand = self.breakers[name], inputs.reverse[f"feeder[{key}]"]
            assert isinstance(demand, ElectricalDemand)
            live = breaker.closed and self.bus.energized
            load_kw = demand.kw if live else 0.0
            fault_a = breaker.fault_a if live else 0.0
            served += load_kw
            fault_total += fault_a
            self._relay(name, load_kw, load_kw / self.kw_per_amp + fault_a, now)
        share = len(in_service)
        for name in INCOMERS:
            carrying = name in in_service
            kw = served / share if carrying else 0.0
            amps = (served / self.kw_per_amp + fault_total) / share if carrying else 0.0
            self._incomer_kw[name] = kw
            self._relay(name, kw, amps + (self.breakers[name].fault_a if carrying else 0.0), now)
        self._served_kw = served
        self._bus_elements(now)
        self._changed = before != self.snapshot()

    def _relay(self, name: str, kw: float, amps: float, now: int) -> None:
        io, breaker = self.io, self.breakers[name]
        operated = breaker.protect(
            amps,
            io.number(f"{name}_pickup_a"),
            io.number(f"{name}_tms"),
            io.number(f"{name}_inst_a"),
            now,
            self.ctx.step_ms,
            self.instantaneous_ms,
            self.breaker_ms,
        )
        io[f"{name}_current_a"], io[f"{name}_kw"] = amps, kw
        io[f"{name}_brk_closed"], io[f"{name}_trip"] = breaker.closed, breaker.trip
        io[f"{name}_operate_s"] = breaker.operate_s
        if operated:
            self.ctx.publish(
                "protection.trip",
                {
                    "relay": "IED-" + name.upper().replace("_", "-"),
                    "element": breaker.trip,
                    "operate_s": breaker.operate_s,
                    "current_a": amps,
                },
            )

    def _bus_elements(self, now: int) -> None:
        io = self.io
        delay_ms = round(io.number("bus_element_delay_s") * 1000)
        limits = {"low_pu": self.low_pu, "high_pu": self.high_pu}
        for flag, measured, limit, sign in BUS_ELEMENTS:
            outside = self.bus.energized and sign * (io.number(measured) - limits[limit]) > 0.0
            if not outside:
                self.bus_since_ms[flag], io[flag] = -1, False
            elif self.bus_since_ms[flag] < 0:
                self.bus_since_ms[flag] = now
            elif now - self.bus_since_ms[flag] >= delay_ms:
                io[flag] = True

    def quiescent(self) -> bool:
        """Nothing changes when no element is timing and the last step changed nothing."""
        timing = any(b.timing() for b in self.breakers.values())
        waiting = any(s >= 0 and not self.io.flag(f) for f, s in self.bus_since_ms.items())
        return not (timing or waiting or self._changed)

    def forward_outputs(self) -> Mapping[str, object]:
        """Return the state of each feeder: the bus, where its breaker is closed."""
        return {
            f"feeder[{key}]": self.bus if self.breakers[name].closed else DEAD
            for key, name in self.feeders.items()
        }

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the demand on each incomer: an equal share for those in service."""
        return {
            "incomer_1": ElectricalDemand(kw=self._incomer_kw["inc_1"]),
            "incomer_2": ElectricalDemand(kw=self._incomer_kw["inc_2"]),
        }

    def power_balance(self) -> dict[str, float]:
        """The switchboard passes power through."""
        drawn = self._incomer_kw["inc_1"] + self._incomer_kw["inc_2"]
        return {"in_kw": drawn, "out_kw": self._served_kw, "loss_kw": 0.0, "stored_kw": 0.0}

    def relay_tags(self) -> tuple[str, ...]:
        """Return the tags of the six relays: the bus relay and one per breaker."""
        return ("IED-BUS", *("IED-" + name.upper().replace("_", "-") for name in self.breakers))

    def _refuse_remote(self, params: Mapping[str, JsonValue]) -> None:
        relay, service = str(params.get("relay")), str(params.get("service"))
        if relay not in self.relay_tags():
            raise ModuleContractError(f"{self.ctx.name}: no relay {relay!r}")
        if service not in REMOTE_SERVICES:
            raise ModuleContractError(f"{self.ctx.name}: no remote service {service!r}")
        self.ctx.publish(
            "protection.refused",
            {
                "relay": relay,
                "service": service,
                "client": str(params.get("client", "")),
                "reason": "nothing in a relay is operated or set over the network",
            },
        )

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the faults or local actions listed in ``faults.py``."""
        if fault == "remote_request":
            self._refuse_remote(params)
            return
        if fault not in ACTIONS:
            super().inject(fault, **params)
            return
        breaker = self.breakers[self._node(params.get("node", params.get("breaker")))]
        if fault == "fault_current":
            breaker.fault_a = float(params["amps"])  # type: ignore[arg-type]
        elif fault == "clear_fault":
            breaker.fault_a = 0.0
        elif fault == "reset":
            breaker.reset()
        elif fault == "manual_open":
            breaker.closed = False
        elif breaker.trip == "NONE":
            breaker.closed = True
        self._changed = True
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state of the switchboard."""
        return {
            "io": self.io.snapshot(),
            "breakers": {name: b.snapshot() for name, b in self.breakers.items()},
            "bus": [self.bus.energized, self.bus.voltage_pu, self.bus.frequency_pu],
            "bus_since_ms": dict(self.bus_since_ms),
            "incomer_kw": dict(self._incomer_kw),
            "served_kw": self._served_kw,
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("switchboard snapshot must be a mapping")
        self.io.restore(state["io"])
        breakers, bus = state["breakers"], state["bus"]
        since, incomer = state["bus_since_ms"], state["incomer_kw"]
        assert isinstance(breakers, Mapping) and isinstance(bus, list | tuple)
        assert isinstance(since, Mapping) and isinstance(incomer, Mapping)
        self.breakers = {name: ProtectedBreaker.restore(b) for name, b in breakers.items()}
        self.bus = ElectricalSupply(bool(bus[0]), float(bus[1]), float(bus[2]))
        self.bus_since_ms = {str(k): int(str(v)) for k, v in since.items()}
        self._incomer_kw = {str(k): float(str(v)) for k, v in incomer.items()}
        self._served_kw = float(state["served_kw"])  # type: ignore[arg-type]
        self._changed = True
