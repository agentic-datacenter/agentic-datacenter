"""The automatic transfer controller of one power train (SDD 7.2).

Open-transition, delayed-transition transfer between utility and generator.
The controller sees its I/O board and the time, and nothing else. It decides
which breaker it wants closed; the hardwired interlock decides whether a close
happens.
"""

from __future__ import annotations

from agentic_datacenter.core.io import IOBoard
from agentic_datacenter.core.state import JsonValue

#: States in which no timer runs: nothing changes until an input does.
TIMERLESS = frozenset({"ON_UTILITY", "ON_GENERATOR", "WAIT_GENERATOR", "LOCKED_OUT"})
_NEEDS_GENERATOR = frozenset({
    "WAIT_GENERATOR", "PRE_TRANSFER", "OPENING_UTILITY", "NEUTRAL_TO_GENERATOR",
    "CLOSING_GENERATOR", "ON_GENERATOR", "RETURN_DELAY", "OPENING_GENERATOR",
    "NEUTRAL_TO_UTILITY", "CLOSING_UTILITY", "GENERATOR_FAULT",
})  # fmt: skip


class TransferController:
    """State machine of the automatic transfer sequence."""

    def __init__(self) -> None:
        """Start on utility with no timer running."""
        self.state = "ON_UTILITY"
        self.since_ms = 0
        self.utility_ok = True
        self.cooldown_until_ms = 0

    # -- helpers ---------------------------------------------------------------

    def _go(self, state: str, now_ms: int) -> None:
        self.state, self.since_ms = state, now_ms

    def _elapsed(self, io: IOBoard, setting: str, now_ms: int) -> bool:
        return now_ms - self.since_ms >= round(io.number(setting) * 1000)

    @staticmethod
    def _within(io: IOBoard, value: float, low: str, high: str) -> bool:
        return io.number(low) <= value <= io.number(high)

    def _accept_utility(self, io: IOBoard) -> bool:
        """Source acceptance with drop-out and pick-up limits on voltage and frequency."""
        volts, hertz = io.number("util_v_pu"), io.number("util_f_pu")
        if self.utility_ok:
            limits = ("dropout_low_pu", "dropout_high_pu")
        else:
            limits = ("pickup_low_pu", "pickup_high_pu")
        self.utility_ok = self._within(io, volts, *limits) and self._within(io, hertz, *limits)
        return self.utility_ok and io["util_brk_trip"] == "NONE"

    def _resync(self, io: IOBoard, now_ms: int) -> None:
        """Take the state from where the breakers are, after a reset or a mode change."""
        if io.flag("util_brk_closed"):
            self._go("ON_UTILITY", now_ms)
        elif io.flag("gen_brk_closed"):
            self._go("ON_GENERATOR", now_ms)
        else:
            self._go("NEUTRAL_TO_UTILITY", now_ms)

    def reset(self, io: IOBoard, now_ms: int) -> None:
        """Manual reset at the device: clear latched alarms and resynchronize."""
        for name in io:
            if name.startswith("alarm_") and name != "alarm_not_in_auto":
                io[name] = False
        self._resync(io, now_ms)

    # -- one scan --------------------------------------------------------------

    def step(self, io: IOBoard, now_ms: int) -> None:
        """Run one scan of the sequence."""
        utility_ok = self._accept_utility(io)
        generator_ok = io.flag("gen_ready") and not io.flag("gen_fault")
        auto = io["mode"] == "AUTO"
        io["alarm_not_in_auto"] = not auto

        if io["util_brk_trip"] == "PROTECTIVE" or io["gen_brk_trip"] == "PROTECTIVE":
            io["alarm_lockout"] = True
            io["util_brk_close_cmd"] = io["gen_brk_close_cmd"] = False
            io["gen_start_request"] = False
            if self.state != "LOCKED_OUT":
                self._go("LOCKED_OUT", now_ms)
            io["state"] = self.state
            return
        if not auto:
            # The automatic sequence is suspended; breakers stay where they are.
            io["gen_start_request"] = False
            self.cooldown_until_ms = 0
            self._resync(io, now_ms)
            io["state"] = self.state
            return
        if self.state == "LOCKED_OUT":
            io["state"] = self.state
            return

        self._sequence(io, now_ms, utility_ok, generator_ok)
        needs_generator = self.state in _NEEDS_GENERATOR
        io["gen_start_request"] = needs_generator or now_ms < self.cooldown_until_ms
        io["state"] = self.state

    def _sequence(self, io: IOBoard, now_ms: int, utility_ok: bool, generator_ok: bool) -> None:
        state = self.state
        io["alarm_gen_fault"] = io.flag("gen_fault")

        if state == "ON_UTILITY":
            blocked = io.flag("alarm_util_brk_fail_open") or io.flag("alarm_gen_brk_fail_close")
            if not utility_ok and not blocked:
                self._go("START_DELAY", now_ms)
        elif state == "START_DELAY":
            if utility_ok:
                self._go("ON_UTILITY", now_ms)
            elif self._elapsed(io, "tdes_s", now_ms):
                self._go("WAIT_GENERATOR", now_ms)
        elif state == "WAIT_GENERATOR":
            if utility_ok:
                self._back_to_utility_with_cooldown(io, now_ms)
            elif generator_ok:
                self._go("PRE_TRANSFER", now_ms)
        elif state == "PRE_TRANSFER":
            if utility_ok:
                self._back_to_utility_with_cooldown(io, now_ms)
            elif not generator_ok:
                self._go("WAIT_GENERATOR", now_ms)
            elif self._elapsed(io, "tdne_s", now_ms):
                io["util_brk_close_cmd"] = False
                self._go("OPENING_UTILITY", now_ms)
        elif state == "OPENING_UTILITY":
            if not io.flag("util_brk_closed"):
                self._go("NEUTRAL_TO_GENERATOR", now_ms)
            elif self._elapsed(io, "feedback_s", now_ms):
                # Utility breaker fails to open: leave the generator out and stop it.
                io["alarm_util_brk_fail_open"] = True
                io["util_brk_close_cmd"] = True
                self._go("ON_UTILITY", now_ms)
        elif state == "NEUTRAL_TO_GENERATOR":
            if self._elapsed(io, "tdpt_s", now_ms):
                if generator_ok:
                    io["gen_brk_close_cmd"] = True
                    self._go("CLOSING_GENERATOR", now_ms)
                elif utility_ok:
                    self._go("NEUTRAL_TO_UTILITY", now_ms - round(io.number("tdpt_s") * 1000))
        elif state == "CLOSING_GENERATOR":
            if io.flag("gen_brk_closed"):
                io["transfers"] = int(io["transfers"]) + 1
                self._go("ON_GENERATOR", now_ms)
            elif self._elapsed(io, "feedback_s", now_ms):
                # Generator breaker fails to close: return to the utility breaker, stop the set.
                io["alarm_gen_brk_fail_close"] = True
                io["gen_brk_close_cmd"] = False
                io["util_brk_close_cmd"] = True
                self._go("CLOSING_UTILITY", now_ms)
        elif state in ("ON_GENERATOR", "RETURN_DELAY"):
            self._on_generator(io, now_ms, utility_ok)
        elif state == "OPENING_GENERATOR":
            if not io.flag("gen_brk_closed"):
                self._go("NEUTRAL_TO_UTILITY", now_ms)
            elif self._elapsed(io, "feedback_s", now_ms):
                # Generator breaker fails to open: keep the utility breaker open.
                io["alarm_gen_brk_fail_open"] = True
                io["gen_brk_close_cmd"] = True
                self._go("ON_GENERATOR", now_ms)
        elif state == "NEUTRAL_TO_UTILITY":
            if self._elapsed(io, "tdpt_s", now_ms):
                failed = io.flag("alarm_util_brk_fail_close")
                if utility_ok and not failed:
                    io["util_brk_close_cmd"] = True
                    self._go("CLOSING_UTILITY", now_ms)
                elif generator_ok and io["gen_brk_trip"] == "NONE":
                    io["gen_brk_close_cmd"] = True
                    self._go("CLOSING_GENERATOR", now_ms)
        elif state == "CLOSING_UTILITY":
            if io.flag("util_brk_closed"):
                self._back_to_utility_with_cooldown(io, now_ms)
            elif self._elapsed(io, "feedback_s", now_ms):
                # Utility breaker fails to close: transfer back to the generator.
                io["alarm_util_brk_fail_close"] = True
                io["util_brk_close_cmd"] = False
                self._go("NEUTRAL_TO_GENERATOR", now_ms)
        elif state == "GENERATOR_FAULT":
            if utility_ok and not io.flag("alarm_util_brk_fail_close"):
                self._go("NEUTRAL_TO_UTILITY", now_ms)
            elif generator_ok and io["gen_brk_trip"] == "NONE":
                self._go("NEUTRAL_TO_GENERATOR", now_ms)

    def _on_generator(self, io: IOBoard, now_ms: int, utility_ok: bool) -> None:
        if io.flag("gen_fault"):
            # Generator fault: open its breaker; no reclose until the fault clears.
            io["gen_brk_close_cmd"] = False
            self._go("GENERATOR_FAULT", now_ms)
            return
        if not io.flag("gen_brk_closed") and io["gen_brk_trip"] != "NONE":
            # The generator breaker tripped: skip TDEN and retransfer at once.
            io["gen_brk_close_cmd"] = False
            self._go("NEUTRAL_TO_UTILITY", now_ms)
            return
        returning = (
            utility_ok
            and not io.flag("alarm_gen_brk_fail_open")
            and not io.flag("alarm_util_brk_fail_close")
        )
        if self.state == "ON_GENERATOR":
            if returning:
                self._go("RETURN_DELAY", now_ms)
        elif not returning:
            # Utility fails during retransfer: stay on the generator; TDEN restarts.
            self._go("ON_GENERATOR", now_ms)
        elif self._elapsed(io, "tden_s", now_ms):
            io["gen_brk_close_cmd"] = False
            self._go("OPENING_GENERATOR", now_ms)

    def _back_to_utility_with_cooldown(self, io: IOBoard, now_ms: int) -> None:
        stopping = io.flag("alarm_gen_brk_fail_close") or io.flag("alarm_util_brk_fail_open")
        if io.flag("gen_start_request") and not stopping:
            self.cooldown_until_ms = now_ms + round(io.number("tdec_s") * 1000)
        self._go("ON_UTILITY", now_ms)

    # -- state -----------------------------------------------------------------

    def snapshot(self) -> JsonValue:
        """Return the controller state that is not on the I/O board."""
        return [self.state, self.since_ms, self.utility_ok, self.cooldown_until_ms]

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, list | tuple) or len(state) != 4:
            raise ValueError("controller snapshot is malformed")
        self.state, self.since_ms, self.utility_ok, self.cooldown_until_ms = state  # type: ignore[assignment]
