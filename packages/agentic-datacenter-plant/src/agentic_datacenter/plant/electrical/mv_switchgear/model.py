"""Protection elements and breakers of the 36 kV switchboard."""

from __future__ import annotations

import math
from dataclasses import dataclass

from agentic_datacenter.core.state import JsonValue


def standard_inverse_s(multiple: float, tms: float) -> float:
    """Return the operating time of the IEC standard inverse characteristic.

    ``t = TMS * 0.14 / ((I / Is) ** 0.02 - 1)`` for a current above pickup, and
    no operation at or below it.

    Args:
        multiple: Current as a multiple of the pickup current, ``I / Is``.
        tms: Time multiplier setting.
    """
    if multiple <= 1.0:
        return math.inf
    return float(tms * 0.14 / (multiple**0.02 - 1.0))


@dataclass
class ProtectedBreaker:
    """One breaker with its overcurrent relay.

    The inverse-time element integrates like an induction disc: each step adds
    the fraction ``dt / t(I)`` of the travel to operation, and the element
    resets at once when the current falls to pickup or below. When the travel
    completes inside a step, the exact instant is kept, so the operating time
    does not depend on the step length.

    Attributes:
        closed: The contacts are closed.
        trip: ``NONE``, or the element that tripped the breaker and holds it
            open until reset: ``PTOC`` (inverse time) or ``PIOC`` (instantaneous).
        travel: Fraction of the inverse-time element's travel, 0 to 1.
        picked_up_ms: Time above pickup so far, in milliseconds.
        open_due_ms: When a tripped breaker's contacts part, or -1.
        operate_s: Time from pickup to operation at the last trip.
        fault_a: Fault current injected at this node by a scenario.
    """

    closed: bool = True
    trip: str = "NONE"
    travel: float = 0.0
    picked_up_ms: float = 0.0
    open_due_ms: float = -1.0
    operate_s: float = 0.0
    fault_a: float = 0.0

    def protect(
        self,
        current_a: float,
        pickup_a: float,
        tms: float,
        instantaneous_a: float,
        now_ms: int,
        step_ms: int,
        instantaneous_ms: float,
        breaker_ms: float,
    ) -> bool:
        """Run the relay for one step; return True if it operated in this step."""
        if self.trip != "NONE" or not self.closed:
            return False
        if current_a >= instantaneous_a:
            self._operate("PIOC", instantaneous_ms, now_ms, breaker_ms)
            return True
        time_s = standard_inverse_s(current_a / pickup_a, tms)
        if math.isinf(time_s):
            self.travel, self.picked_up_ms = 0.0, 0.0
            return False
        remaining_ms = (1.0 - self.travel) * time_s * 1000.0
        if remaining_ms <= step_ms:
            self._operate(
                "PTOC", self.picked_up_ms + remaining_ms, now_ms, breaker_ms, offset_ms=remaining_ms
            )
            return True
        self.travel += step_ms / (time_s * 1000.0)
        self.picked_up_ms += step_ms
        return False

    def _operate(
        self,
        element: str,
        elapsed_ms: float,
        now_ms: int,
        breaker_ms: float,
        offset_ms: float | None = None,
    ) -> None:
        within_step = elapsed_ms if offset_ms is None else offset_ms
        self.trip, self.operate_s = element, elapsed_ms / 1000.0
        self.open_due_ms = now_ms + within_step + breaker_ms
        self.travel, self.picked_up_ms = 0.0, 0.0

    def part_contacts(self, now_ms: int) -> None:
        """Open the breaker once a trip's breaker operating time has passed."""
        if self.open_due_ms >= 0.0 and now_ms >= self.open_due_ms:
            self.closed, self.open_due_ms = False, -1.0

    def timing(self) -> bool:
        """An element is travelling or a trip is waiting for the contacts to part."""
        return self.travel > 0.0 or self.open_due_ms >= 0.0

    def reset(self) -> None:
        """Manual reset at the relay: clear the trip and close the breaker."""
        self.closed, self.trip, self.open_due_ms = True, "NONE", -1.0
        self.travel, self.picked_up_ms = 0.0, 0.0

    def snapshot(self) -> JsonValue:
        """Return the breaker and relay state."""
        return [
            self.closed,
            self.trip,
            self.travel,
            self.picked_up_ms,
            self.open_due_ms,
            self.operate_s,
            self.fault_a,
        ]

    @classmethod
    def restore(cls, state: JsonValue) -> ProtectedBreaker:
        """Rebuild from :meth:`snapshot` output."""
        if not isinstance(state, list | tuple) or len(state) != 7:
            raise ValueError("breaker snapshot is malformed")
        return cls(*state)
