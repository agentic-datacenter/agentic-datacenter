"""Zones and conduits of the facility (SDD 4.1, 4.2; ``docs/design/zone_model.md``).

Deny is the default. A flow between two zones is possible only when a conduit
joins them in that direction, and then only for what the conduit carries. The
model here is data: the virtual network of ``inproc`` mode and, later, the
conduit containers of ``compose`` mode are both driven by it.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from agentic_datacenter.core.registry import Plant

SUP, SEC, DMZ, AGENT, ENT, PROT = "Z2-SUP", "Z2-SEC", "Z3-DMZ", "ZA-AGENT", "Z4-ENT", "Z0-PROT"
#: Zones that exist in every facility, whether or not a module sits in them.
FIXED_ZONES = (PROT, "Z1-MV", "Z1-BLDG", SUP, SEC, DMZ, AGENT, ENT)
#: Hosts in ``Z2-SUP`` that may read from controllers, and the one that may write.
SUPERVISORY_READERS = ("bms", "pms", "historian", "command-service")
COMMAND_SERVICE, GATE, READ_API, JUMP_HOST = "command-service", "gate", "read-api", "jump-host"


def is_level_one(zone: str) -> bool:
    """Return whether *zone* is a level 1 (controller) zone."""
    return zone.startswith("Z1-")


def zone_instances(plant: Plant) -> list[str]:
    """Return every zone instance of *plant*, sorted: its modules' zones and the fixed ones."""
    zones = {manifest.zone_for(module.ctx.instance) for _, manifest, module in plant.instances()}
    # A module that is a service of the simulator, not a device, has zone "n/a".
    return sorted({z for z in zones if z.startswith("Z")} | set(FIXED_ZONES))


@dataclass(frozen=True)
class Conduit:
    """One conduit: who may open it, toward whom, and what it carries.

    Attributes:
        conduit_id: ``C1`` to ``C8``.
        initiator: The zone that opens the connection, or ``Z1-*`` for every level 1 zone.
        responder: The zone that answers, or ``Z1-*``.
        protocols: What the conduit carries.
        initiator_host: The only host that may open it, if it is restricted to one.
        responder_host: The only host it reaches, if it is restricted to one.
        read_only: Nothing may be written through it.
        rule: The rule the simulator enforces, in words.
    """

    conduit_id: str
    initiator: str
    responder: str
    protocols: tuple[str, ...]
    initiator_host: str = ""
    responder_host: str = ""
    read_only: bool = False
    rule: str = ""

    def joins(self, source: str, destination: str) -> bool:
        """Return whether this conduit runs from zone *source* to zone *destination*."""
        return _matches(self.initiator, source) and _matches(self.responder, destination)


def _matches(pattern: str, zone: str) -> bool:
    return is_level_one(zone) if pattern == "Z1-*" else pattern == zone


CONDUITS: tuple[Conduit, ...] = (
    Conduit("C1", SUP, "Z1-*", ("modbus", "bacnet", "snmp", "mms"),
            rule="allowlist of device, operation and address; writes from the command service"),
    Conduit("C2", SUP, DMZ, ("opcua", "historian", "ntp"), read_only=True,
            rule="opened from the supervisory side only; data flows outward"),
    Conduit("C3", ENT, DMZ, ("https",), responder_host=READ_API, read_only=True,
            rule="read-only API; no command verbs"),
    Conduit("C4", AGENT, DMZ, ("https", "mcp"), responder_host=GATE,
            rule="reads and proposals to the gate only; identity from the client certificate"),
    Conduit("C5", DMZ, SUP, ("https",), initiator_host=GATE, responder_host=COMMAND_SERVICE,
            rule="gate to command service only; every request carries a decision reference"),
    Conduit("C6", PROT, "Z1-*", ("contact",), read_only=True,
            rule="hardwired contacts, one way; there is no reverse path"),
    Conduit("C6", PROT, SUP, ("contact",), read_only=True,
            rule="hardwired contacts, one way; there is no reverse path"),
    Conduit("C7", ENT, DMZ, ("session",), responder_host=JUMP_HOST,
            rule="brokered remote session to the jump host"),
    Conduit("C7", DMZ, SUP, ("session",), initiator_host=JUMP_HOST,
            rule="brokered session from the jump host; time-boxed, tied to a work permit"),
    Conduit("C8", SEC, SUP, ("events",), read_only=True,
            rule="one-way event feed; no door command is accepted"),
)  # fmt: skip


def conduits_between(
    source: str, destination: str, conduits: Sequence[Conduit] = CONDUITS
) -> list[Conduit]:
    """Return the conduits that run from zone *source* to zone *destination*."""
    return [c for c in conduits if c.joins(source, destination)]


def allowed_pairs(zones: Iterable[str]) -> set[tuple[str, str]]:
    """Return every ordered pair of distinct zones that some conduit joins."""
    listed = list(zones)
    return {
        (source, destination)
        for source in listed
        for destination in listed
        if source != destination and conduits_between(source, destination)
    }
