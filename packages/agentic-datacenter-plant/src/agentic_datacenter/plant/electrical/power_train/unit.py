"""One 400/230 V power train: switchboard, source breakers and transfer controller."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from agentic_datacenter.core.io import IOBoard, load_points
from agentic_datacenter.core.module import Inputs, ModuleContext, ModuleContractError, SimModule
from agentic_datacenter.core.ports import ElectricalDemand, ElectricalSupply, Signal
from agentic_datacenter.core.state import JsonValue

from .controller import TIMERLESS, TransferController
from .faults import ACTIONS, STUCK, TRIPS
from .model import DEAD, Breaker, Switchboard

POINTS = load_points(Path(__file__).parent / "points.yaml")
BREAKER_OPERATING_MS = 50  # assumed, SDD 6.1


class PowerTrain(SimModule):
    """Power train at fidelity F1: correct states, sequence and timers."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create a train on utility; ``params`` may override any setting point."""
        super().__init__(ctx, params)
        self.io = IOBoard(POINTS)
        for name, value in params.items():
            self.io[name] = value  # type: ignore[assignment]
        self.board = Switchboard(BREAKER_OPERATING_MS)
        self.controller = TransferController()
        # The plant starts in normal operation: on utility, bus live.
        self._source = "utility"
        self._bus = ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0)
        self._demand_kw = 0.0
        self._idle = False

    # -- stepping --------------------------------------------------------------

    def step(self, inputs: Inputs) -> None:
        """Complete breaker operations, scan the controller, act on its commands."""
        now = self.ctx.now_ms
        utility, generator = inputs.forward["utility_feed"], inputs.forward["gen_output"]
        ready, fault = inputs.forward["gen_ready_to_load"], inputs.forward["gen_fault"]
        demand = inputs.reverse["lv_bus"]
        assert isinstance(utility, ElectricalSupply) and isinstance(generator, ElectricalSupply)
        assert isinstance(ready, Signal) and isinstance(fault, Signal)
        assert isinstance(demand, ElectricalDemand)
        before = (
            self.io.snapshot(),
            self.board.utility.snapshot(),
            self.board.generator.snapshot(),
        )

        self.board.complete_operations(now)
        io = self.io
        io["util_v_pu"], io["util_f_pu"] = utility.voltage_pu, utility.frequency_pu
        io["gen_v_pu"], io["gen_f_pu"] = generator.voltage_pu, generator.frequency_pu
        io["gen_ready"], io["gen_fault"] = ready.active, fault.active
        io["util_brk_closed"] = self.board.utility.closed
        io["gen_brk_closed"] = self.board.generator.closed
        io["util_brk_trip"], io["gen_brk_trip"] = self.board.utility.trip, self.board.generator.trip
        previous = self.controller.state
        if self.ctx.controller_running():
            self.controller.step(io, now)
        if self.controller.state != previous:
            self.ctx.publish("ato.state", {"state": self.controller.state, "from": previous})
        self.board.command(io.flag("util_brk_close_cmd"), io.flag("gen_brk_close_cmd"), now)

        self._source, self._bus = self.board.bus(utility, generator)
        self._demand_kw = demand.kw if self._source else 0.0
        io["bus_kw"] = self._demand_kw
        after = (io.snapshot(), self.board.utility.snapshot(), self.board.generator.snapshot())
        self._idle = (
            before == after
            and self.controller.state in TIMERLESS
            and now >= self.controller.cooldown_until_ms
        )

    def quiescent(self) -> bool:
        """True when no timer runs, no breaker moves and the last scan changed nothing."""
        return self._idle

    def forward_outputs(self) -> Mapping[str, object]:
        """Return the bus state and the generator start request."""
        return {
            "lv_bus": self._bus if self._source else self._initial_bus(),
            "gen_start_request": Signal(active=self.io.flag("gen_start_request")),
        }

    def _initial_bus(self) -> ElectricalSupply:
        return DEAD

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the demand placed on each source: all of it on the one carrying the bus."""
        return {
            "utility_feed": ElectricalDemand(self._demand_kw if self._source == "utility" else 0.0),
            "gen_output": ElectricalDemand(self._demand_kw if self._source == "generator" else 0.0),
        }

    def power_balance(self) -> dict[str, float]:
        """The switchboard passes power through: what the bus draws, the source supplies."""
        return {
            "in_kw": self._demand_kw,
            "out_kw": self._demand_kw,
            "loss_kw": 0.0,
            "stored_kw": 0.0,
        }

    # -- faults and local actions -----------------------------------------------

    def _breaker(self, name: str) -> Breaker:
        if name not in ("util", "gen"):
            raise ModuleContractError(f"{self.ctx.name}: no breaker {name!r}")
        return self.board.utility if name == "util" else self.board.generator

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the faults or local actions listed in ``faults.py``."""
        if fault in STUCK:
            which, _, mode = fault.partition("_brk_")
            setattr(self._breaker(which), mode, True)
        elif fault in TRIPS:
            kind = str(params.get("kind", "protective")).upper()
            if kind not in ("PROTECTIVE", "OTHER"):
                raise ModuleContractError(f"{self.ctx.name}: unknown trip kind {kind!r}")
            self._breaker(fault.partition("_brk_")[0]).trip_open(kind)
        elif fault == "clear_faults":
            for source in (self.board.utility, self.board.generator):
                source.fail_open = source.fail_close = False
        elif fault == "reset":
            self.board.utility.trip = self.board.generator.trip = "NONE"
            self.io["util_brk_trip"] = self.io["gen_brk_trip"] = "NONE"
            self.io["util_brk_closed"] = self.board.utility.closed
            self.io["gen_brk_closed"] = self.board.generator.closed
            self.controller.reset(self.io, self.ctx.now_ms)
        elif fault == "set_mode":
            self.io["mode"] = str(params["mode"])
        elif fault in ("manual_close", "manual_open"):
            point = f"{params['breaker']}_brk_close_cmd"
            self._breaker(str(params["breaker"]))
            self.io[point] = fault == "manual_close"
        else:
            assert fault not in ACTIONS
            super().inject(fault, **params)
            return
        self._idle = False
        self.ctx.wake()

    # -- state -------------------------------------------------------------------

    def snapshot(self) -> JsonValue:
        """Return the complete state of the train."""
        return {
            "io": self.io.snapshot(),
            "controller": self.controller.snapshot(),
            "utility_breaker": self.board.utility.snapshot(),
            "generator_breaker": self.board.generator.snapshot(),
            "bus": [
                self._source,
                self._bus.energized,
                self._bus.voltage_pu,
                self._bus.frequency_pu,
                self._demand_kw,
                self._idle,
            ],
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("power-train snapshot must be a mapping")
        self.io.restore(state["io"])
        self.controller.restore(state["controller"])
        self.board.utility = Breaker.restore(state["utility_breaker"])
        self.board.generator = Breaker.restore(state["generator_breaker"])
        bus = state["bus"]
        assert isinstance(bus, list | tuple)
        self._source = str(bus[0])
        self._bus = ElectricalSupply(bool(bus[1]), float(bus[2]), float(bus[3]))
        self._demand_kw, self._idle = float(bus[4]), bool(bus[5])
