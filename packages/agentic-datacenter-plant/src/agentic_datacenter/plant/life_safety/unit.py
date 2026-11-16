"""Fire and life safety: detection, the panel, hardwired cause and effect, the fire pump."""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path

from agentic_datacenter.core.io import IOBoard, PointDecl, load_points
from agentic_datacenter.core.module import Inputs, ModuleContext, SimModule, param_number
from agentic_datacenter.core.ports import ElectricalDemand, ElectricalSupply, Signal
from agentic_datacenter.core.state import JsonValue

from .faults import FAULTS, LEVELS

TEMPLATE = load_points(Path(__file__).parent / "points.yaml")


def point_key(key: str) -> str:
    """Return *key* in the form it takes inside a point name."""
    return re.sub(r"[^a-z0-9]", "_", key.lower())


def expand_points(pods: tuple[str, ...]) -> tuple[PointDecl, ...]:
    """Return the point list for *pods*: every ``pod_`` point once per POD."""
    out: list[PointDecl] = []
    for decl in TEMPLATE:
        if not decl.name.startswith("pod_"):
            out.append(decl)
            continue
        for pod in pods:
            name = f"pod_{point_key(pod)}_{decl.name[4:]}"
            out.append(
                decl.model_copy(
                    update={"name": name, "description": f"{decl.description} (POD {pod})"}
                )
            )
    return tuple(out)


class LifeSafety(SimModule):
    """Fire and life safety at fidelity F1: discrete, and hardwired.

    Each POD has an air-sampling detector with four escalating thresholds. The
    panel is in pre-alarm from the first threshold and in alarm from the first
    fire threshold. The second fire threshold confirms the fire: the POD's air
    handlers stop and its dampers close, and that stays so until the panel is
    reset with the detector clear. Emergency power off removes power from one
    POD and is latched at its station. The fire pump runs on a sprinkler
    pressure drop and asks for a generator through its own transfer switch.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create a quiet building."""
        super().__init__(ctx, params)
        self.pods = tuple(ctx.keys["pods"])
        self.io = IOBoard(expand_points(self.pods))
        self.pump_kw = param_number(params, "fire_pump_kw", 75.0)
        self.smoke = dict.fromkeys(self.pods, "NORMAL")
        self.confirmed = dict.fromkeys(self.pods, False)
        self.epo = dict.fromkeys(self.pods, False)
        self.panel_fault = False
        self.pressure_ok = True
        self.pump_failed = False
        self.pump_running = False
        self._dirty = True

    def step(self, inputs: Inputs) -> None:
        """Evaluate the panel and the cause-and-effect matrix."""
        feed = inputs.forward["power"]
        assert isinstance(feed, ElectricalSupply)
        io = self.io
        worst = 0
        for pod in self.pods:
            level = LEVELS.index(self.smoke[pod])
            worst = max(worst, level)
            if level == len(LEVELS) - 1:
                self.confirmed[pod] = True
            key = point_key(pod)
            io[f"pod_{key}_smoke_level"] = self.smoke[pod]
            io[f"pod_{key}_fire_confirmed"] = self.confirmed[pod]
            io[f"pod_{key}_epo_active"] = self.epo[pod]
        fault = self.panel_fault or not feed.energized
        fire = worst >= LEVELS.index("FIRE_1") or any(self.confirmed.values())
        if fire:
            state = "ALARM"
        elif worst > 0:
            state = "PRE_ALARM"
        else:
            state = "FAULT" if fault else "NORMAL"
        called = not self.pressure_ok
        # The pump has its own transfer switch: it runs when either source is there.
        self.pump_running = called and feed.energized and not self.pump_failed
        io["panel_state"], io["alarm_fire"], io["alarm_panel_fault"] = state, fire, fault
        io["sprinkler_pressure_ok"], io["fire_pump_called"] = self.pressure_ok, called
        io["fire_pump_running"] = self.pump_running
        io["alarm_fire_pump_failed"] = called and not self.pump_running
        io["power_kw"] = self.pump_kw if self.pump_running else 0.0
        self._dirty = False

    def quiescent(self) -> bool:
        """Nothing changes until something happens at the equipment or the supply changes."""
        return not self._dirty

    def forward_outputs(self) -> Mapping[str, object]:
        """Return the hardwired signals."""
        out: dict[str, object] = {"fire_pump_start_request": Signal(active=not self.pressure_ok)}
        for pod in self.pods:
            out[f"pod_fire[{pod}]"] = Signal(active=self.confirmed[pod])
            out[f"pod_epo[{pod}]"] = Signal(active=self.epo[pod])
        return out

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the power the fire pump draws."""
        return {"power": ElectricalDemand(kw=self.pump_kw if self.pump_running else 0.0)}

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the events listed in ``faults.py``."""
        if fault not in FAULTS:
            super().inject(fault, **params)
            return
        if fault in ("smoke", "epo", "epo_reset"):
            pod = str(params.get("pod", ""))
            if pod not in self.pods:
                raise ValueError(f"pod must be one of the PODs, not {pod!r}")
            if fault == "smoke":
                level = str(params.get("level", ""))
                if level not in LEVELS:
                    raise ValueError(f"level must be one of {list(LEVELS)}")
                self.smoke[pod] = level
            else:
                self.epo[pod] = fault == "epo"
        elif fault == "panel_reset":
            fire_levels = LEVELS[3:]
            for pod in self.pods:
                if self.smoke[pod] not in fire_levels:
                    self.confirmed[pod] = False
        elif fault in ("panel_fault", "panel_fault_clear"):
            self.panel_fault = fault == "panel_fault"
        elif fault in ("sprinkler_pressure_drop", "sprinkler_pressure_restore"):
            self.pressure_ok = fault == "sprinkler_pressure_restore"
        else:
            self.pump_failed = fault == "fire_pump_failure"
        self._dirty = True
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state."""
        return {
            "io": self.io.snapshot(),
            "smoke": dict(self.smoke),
            "confirmed": dict(self.confirmed),
            "epo": dict(self.epo),
            "flags": [self.panel_fault, self.pressure_ok, self.pump_failed, self.pump_running],
            "dirty": self._dirty,
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("life-safety snapshot must be a mapping")
        self.io.restore(state["io"])
        smoke, confirmed, epo, flags = (state[k] for k in ("smoke", "confirmed", "epo", "flags"))
        if not (
            isinstance(smoke, Mapping)
            and isinstance(confirmed, Mapping)
            and isinstance(epo, Mapping)
        ):
            raise ValueError("life-safety snapshot is malformed")
        assert isinstance(flags, list | tuple)
        self.smoke = {k: str(v) for k, v in smoke.items()}
        self.confirmed = {k: bool(v) for k, v in confirmed.items()}
        self.epo = {k: bool(v) for k, v in epo.items()}
        self.panel_fault, self.pressure_ok, self.pump_failed, self.pump_running = (
            bool(v) for v in flags
        )
        self._dirty = bool(state["dirty"])
