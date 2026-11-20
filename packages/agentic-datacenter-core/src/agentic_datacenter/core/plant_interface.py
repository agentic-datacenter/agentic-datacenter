"""The plant interface: what the harness and the oracle need of a plant (ADR 0029).

The built-in plant is one implementation. A plant served by another project
is another. The harness and the oracle reach a plant through this interface
only (ADC-PLT-001).

The oracle measures harm from a plant's true state, not from its points, so a
plant gives its true state on a channel of its own (:class:`Harm`).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from agentic_datacenter.core.state import JsonValue

#: What the oracle reads of a plant's true state. Each is one channel; a plant
#: that does not offer a channel says so in :attr:`PlantDescription.harm_channels`.
HARM_CHANNELS = ("supply_air_c", "it_served_kw", "it_kwh_lost", "facility_in_kw", "both_closed")


@dataclass(frozen=True)
class PointInfo:
    """One point as a plant declares it. Tiers ``T2`` and ``T3`` can be written."""

    tag: str
    kind: str
    tier: str
    unit: str
    range: tuple[float, float] | None
    description: str
    zone: str


@dataclass(frozen=True)
class PlantDescription:
    """What a plant is, what it offers, and what it can be asked to do."""

    name: str
    version: str
    #: The owner's own statement of how far the plant can be believed, verbatim.
    fidelity: str
    #: The plant's step in simulated milliseconds. It divides 1000.
    step_ms: int
    points: tuple[PointInfo, ...]
    #: Every target an event can be injected into, with the faults it accepts.
    faults: Mapping[str, tuple[str, ...]]
    #: Every protection relay, with the target that owns it and that target's zone.
    relays: Mapping[str, tuple[str, str]]
    harm_channels: tuple[str, ...]
    #: Whether :meth:`PlantModel.capture` returns something a branch can start from.
    offers_capture: bool


@dataclass(frozen=True)
class Harm:
    """A plant's true state, as the oracle reads it, at one instant.

    Each tuple has one entry per space, load, source or train, in the plant's
    own order, so that sums are taken in the same order on every run.
    """

    #: True supply or intake air of every space, °C.
    supply_air_c: tuple[float, ...]
    #: IT power served by every IT load, kW.
    it_served_kw: tuple[float, ...]
    #: IT energy not served since the start, by every IT load, kWh.
    it_kwh_lost: tuple[float, ...]
    #: Power drawn from outside the facility at every incomer, kW.
    facility_in_kw: tuple[float, ...]
    #: For every power train, whether both its sources are closed at once.
    both_closed: tuple[bool, ...]


@runtime_checkable
class PlantModel(Protocol):
    """A plant, as the harness and the oracle see it."""

    def describe(self) -> PlantDescription:
        """Return what the plant is and offers."""
        ...

    def harm(self) -> Harm:
        """Return the plant's true state, as the oracle reads it, now."""
        ...

    def write(self, tag: str, value: bool | int | float | str) -> bool | int | float | str:
        """Write a declared point and return the value it replaced."""
        ...

    def inject(self, target: str, fault: str, params: Mapping[str, JsonValue]) -> None:
        """Inject *fault* into *target*. A fault the plant did not declare is refused."""
        ...

    def capture(self) -> JsonValue:
        """Return the plant's state, to start a branch from; None when it is held elsewhere."""
        ...

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`capture`."""
        ...

    def state_hash(self) -> str:
        """Return the hash of the plant's whole state, as the plant computes it."""
        ...
