"""Process model of one main switchboard: two source breakers and a bus."""

from __future__ import annotations

from dataclasses import dataclass

from agentic_datacenter.core.ports import ElectricalSupply
from agentic_datacenter.core.state import JsonValue

from .interlocks import permit_close

DEAD = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)


@dataclass
class Breaker:
    """A source breaker with an operating time and three failure modes.

    Attributes:
        closed: The main contacts are closed.
        trip: ``NONE``, or the kind of trip that opened the breaker and holds
            it open until a manual reset: ``PROTECTIVE`` (ground fault or
            instantaneous) or ``OTHER``.
        fail_open: An open operation leaves the contacts closed.
        fail_close: A close operation leaves the contacts open.
        pending: The operation under way, ``open`` or ``close``, or empty.
        due_ms: When the operation under way completes.
    """

    closed: bool
    trip: str = "NONE"
    fail_open: bool = False
    fail_close: bool = False
    pending: str = ""
    due_ms: int = 0

    @property
    def closing(self) -> bool:
        """A close operation is under way."""
        return self.pending == "close"

    def command(self, close: bool, now_ms: int, operating_ms: int, permitted: bool) -> None:
        """Start an operation toward the commanded position, if one is needed."""
        wanted = "close" if close else "open"
        if self.pending == wanted or (not self.pending and self.closed == close):
            return
        if close and (self.trip != "NONE" or not permitted):
            self.pending = ""
            return
        self.pending, self.due_ms = wanted, now_ms + operating_ms

    def complete(self, now_ms: int, permitted: bool) -> None:
        """Finish the operation under way once its operating time has passed."""
        if not self.pending or now_ms < self.due_ms:
            return
        if self.pending == "open":
            self.closed = self.closed and self.fail_open
        elif permitted and self.trip == "NONE" and not self.fail_close:
            self.closed = True
        self.pending = ""

    def trip_open(self, kind: str) -> None:
        """Open at once on a trip and hold open until reset."""
        self.closed, self.trip, self.pending = False, kind, ""

    def snapshot(self) -> JsonValue:
        """Return the breaker state."""
        return [self.closed, self.trip, self.fail_open, self.fail_close, self.pending, self.due_ms]

    @classmethod
    def restore(cls, state: JsonValue) -> Breaker:
        """Rebuild a breaker from :meth:`snapshot` output."""
        if not isinstance(state, list | tuple) or len(state) != 6:
            raise ValueError("breaker snapshot is malformed")
        return cls(*state)


class Switchboard:
    """Two source breakers feeding one bus, with the interlock between them."""

    def __init__(self, operating_ms: int) -> None:
        """Create a switchboard on utility, with the generator breaker open."""
        self.operating_ms = operating_ms
        self.utility = Breaker(closed=True)
        self.generator = Breaker(closed=False)

    def complete_operations(self, now_ms: int) -> None:
        """Let operations whose time has passed take effect, utility first."""
        self.utility.complete(
            now_ms, permit_close(other_closed=self.generator.closed, other_closing=False)
        )
        self.generator.complete(
            now_ms,
            permit_close(other_closed=self.utility.closed, other_closing=self.utility.closing),
        )

    def command(self, utility_close: bool, generator_close: bool, now_ms: int) -> None:
        """Pass close and open commands to the breakers through the interlock."""
        self.utility.command(
            utility_close,
            now_ms,
            self.operating_ms,
            permit_close(other_closed=self.generator.closed, other_closing=self.generator.closing),
        )
        self.generator.command(
            generator_close,
            now_ms,
            self.operating_ms,
            permit_close(other_closed=self.utility.closed, other_closing=self.utility.closing),
        )

    def bus(
        self, utility: ElectricalSupply, generator: ElectricalSupply
    ) -> tuple[str, ElectricalSupply]:
        """Return the source carrying the bus (utility, generator or none) and its state."""
        if self.utility.closed:
            return ("utility", utility) if utility.energized else ("", DEAD)
        if self.generator.closed:
            return ("generator", generator) if generator.energized else ("", DEAD)
        return "", DEAD
