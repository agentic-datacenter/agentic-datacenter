"""One online UPS with its battery."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agentic_datacenter.core.io import IOBoard, load_points
from agentic_datacenter.core.module import Inputs, ModuleContext, SimModule
from agentic_datacenter.core.ports import AirHeat, ElectricalDemand, ElectricalSupply
from agentic_datacenter.core.state import JsonValue

from .faults import FAULTS

POINTS = load_points(Path(__file__).parent / "points.yaml")
DEAD = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)
NOMINAL = ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0)


def _number(params: Mapping[str, JsonValue], name: str, default: float) -> float:
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"parameter {name} must be a number")
    return float(value)


class Ups(SimModule):
    """UPS at fidelity F1: modes, battery energy balance, recharge limit, static bypass.

    The battery holds the energy that carries the rated load for the autonomy
    time, measured ahead of the inverter::

        E(t + dt) = E(t) - P_out / efficiency * dt
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create a UPS online with a full battery."""
        super().__init__(ctx, params)
        self.io = IOBoard(POINTS)
        self.rated_kw = _number(params, "rated_kw", 1200.0)
        self.efficiency = _number(params, "efficiency", 0.96)
        self.recharge_kw = _number(params, "recharge_fraction", 0.1) * self.rated_kw
        self.low_pu = _number(params, "input_low_pu", 0.9)
        self.high_pu = _number(params, "input_high_pu", 1.1)
        self.airflow = _number(params, "airflow_kg_s", 4.0)
        autonomy_s = _number(params, "autonomy_s", 300.0)
        self.capacity_kwh = self.rated_kw / self.efficiency * autonomy_s / 3600
        self.energy_kwh = self.capacity_kwh
        self.failed = False
        # The plant starts in normal operation: online, output live.
        self._output = NOMINAL
        self._stored_kw = 0.0

    def _input_ok(self, supply: ElectricalSupply) -> bool:
        return (
            supply.energized
            and self.low_pu <= supply.voltage_pu <= self.high_pu
            and self.low_pu <= supply.frequency_pu <= self.high_pu
        )

    def step(self, inputs: Inputs) -> None:
        """Choose the mode and move energy for one step."""
        supply, demand = inputs.forward["input"], inputs.reverse["output"]
        assert isinstance(supply, ElectricalSupply) and isinstance(demand, ElectricalDemand)
        hours = self.ctx.step_ms / 3_600_000
        load = demand.kw
        before = self.energy_kwh
        drawn = loss = 0.0

        if self.failed:
            mode = "BYPASS"
            self._output = supply if supply.energized else DEAD
            load = load if supply.energized else 0.0
            drawn = load
        elif self._input_ok(supply):
            mode = "ONLINE"
            self._output = NOMINAL
            loss = load / self.efficiency - load
            room_kw = (self.capacity_kwh - self.energy_kwh) / hours
            charge = min(self.recharge_kw, room_kw)
            if charge >= room_kw:
                self.energy_kwh = self.capacity_kwh
            else:
                self.energy_kwh += charge * hours
            drawn = load + loss + charge
        elif self.energy_kwh > 0.0:
            mode = "ON_BATTERY"
            self._output = NOMINAL
            loss = load / self.efficiency - load
            self.energy_kwh = max(0.0, self.energy_kwh - (load + loss) * hours)
            if self.energy_kwh == 0.0:
                mode, self._output = "DEPLETED", DEAD
        else:
            mode, self._output, load = "DEPLETED", DEAD, 0.0

        io = self.io
        if io["mode"] != mode:
            self.ctx.publish("ups.mode", {"mode": mode, "from": io["mode"]})
        self._stored_kw = (self.energy_kwh - before) / hours
        io["mode"] = mode
        io["on_battery_alarm"] = mode == "ON_BATTERY"
        io["soc_pct"] = 100.0 * self.energy_kwh / self.capacity_kwh
        io["output_kw"], io["input_kw"], io["loss_kw"] = load, drawn, loss
        through = load / self.efficiency
        io["autonomy_s"] = self.energy_kwh / through * 3600 if through > 0.0 else 0.0

    def quiescent(self) -> bool:
        """Nothing changes online with a full battery, on bypass, or depleted."""
        mode = self.io["mode"]
        return mode in ("BYPASS", "DEPLETED") or (
            mode == "ONLINE" and self.energy_kwh == self.capacity_kwh
        )

    def forward_outputs(self) -> Mapping[str, object]:
        """Return the output bus state and the heat released to the room."""
        return {
            "output": self._output,
            "heat": AirHeat(heat_kw=self.io.number("loss_kw"), airflow_kg_s=self.airflow),
        }

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the power drawn from the input."""
        return {"input": ElectricalDemand(kw=self.io.number("input_kw"))}

    def power_balance(self) -> dict[str, float]:
        """Input, output, losses and the rate of change of stored energy, in kW."""
        io = self.io
        return {
            "in_kw": io.number("input_kw"),
            "out_kw": io.number("output_kw") if self._output.energized else 0.0,
            "loss_kw": io.number("loss_kw"),
            "stored_kw": self._stored_kw,
        }

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the faults or local actions listed in ``faults.py``."""
        if fault not in FAULTS:
            super().inject(fault, **params)
            return
        if fault == "set_soc":
            pct = float(params["pct"])  # type: ignore[arg-type]
            self.energy_kwh = self.capacity_kwh * min(max(pct, 0.0), 100.0) / 100.0
        else:
            self.failed = fault == "fault"
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state of the UPS."""
        out = self._output
        return {
            "io": self.io.snapshot(),
            "energy_kwh": self.energy_kwh,
            "failed": self.failed,
            "output": [out.energized, out.voltage_pu, out.frequency_pu],
            "stored_kw": self._stored_kw,
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("UPS snapshot must be a mapping")
        self.io.restore(state["io"])
        output = state["output"]
        assert isinstance(output, list | tuple)
        self.energy_kwh = float(state["energy_kwh"])  # type: ignore[arg-type]
        self.failed = bool(state["failed"])
        self._output = ElectricalSupply(bool(output[0]), float(output[1]), float(output[2]))
        self._stored_kw = float(state["stored_kw"])  # type: ignore[arg-type]
