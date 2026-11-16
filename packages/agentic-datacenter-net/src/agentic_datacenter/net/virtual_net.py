"""The virtual network of ``inproc`` mode: zone separation and conduit rules (SDD 4.2).

Every connection and every request between two endpoints of the simulated
facility is put to :meth:`VirtualNetwork.request`. It is allowed only when a
conduit joins the two zones in that direction, carries that protocol, and,
inside conduit ``C1``, when the device, operation and address are on the
allowlist generated from the protocol maps. Into a protection relay the
allowlist is by client, relay and MMS service class: read and report pass,
and control, setting-group, write and file services are dropped (SDD 8.5).
Everything else is refused, and a
refusal is a security event at once: it is written to the violation log and
published on the event bus with source zone, destination and rule
(ADC-NET-003).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from agentic_datacenter.core.registry import Plant
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.net.maps import PointMap, protocol_maps
from agentic_datacenter.net.zones import (
    COMMAND_SERVICE,
    CONDUITS,
    SUPERVISORY_READERS,
    Conduit,
    conduits_between,
    zone_instances,
)
from agentic_datacenter.supervisory.logs import AppendOnlyLog
from agentic_datacenter.supervisory.points import PointDatabase

READ, WRITE, CONNECT = "read", "write", "connect"
#: MMS service classes besides read and write (SDD 8.5, "Security").
REPORT, CONTROL, SETTING_GROUP, FILE = "report", "control", "setting-group", "file"
MMS_PASSED = (CONNECT, READ, REPORT)


@dataclass(frozen=True)
class Request:
    """One attempt to reach something across the facility network.

    Attributes:
        source_zone: Zone of the endpoint that opens the connection.
        source_host: Its host name inside that zone.
        destination_zone: Zone of the endpoint it wants to reach.
        destination_host: Host or device it wants to reach.
        protocol: ``modbus``, ``bacnet``, ``snmp``, ``mms``, ``opcua``,
            ``https``, ``mcp``, ``session``, ``events``, ``contact`` ...
        operation: ``connect``, ``read`` or ``write``; for ``mms`` also the
            service classes ``report``, ``control``, ``setting-group`` and ``file``.
        object_type: Table or object type, for a read or a write.
        address: Register, object instance, identifier or node.
        permit: A work permit covers this session (conduit ``C7``).
    """

    source_zone: str
    source_host: str
    destination_zone: str
    destination_host: str
    protocol: str
    operation: str = CONNECT
    object_type: str = ""
    address: int | str = ""
    permit: bool = False


@dataclass(frozen=True)
class Answer:
    """Whether a request passes, through which conduit, and by which rule."""

    allowed: bool
    conduit: str
    rule: str


class VirtualNetwork:
    """Decides every request, and records every refusal."""

    def __init__(
        self,
        kernel: Kernel,
        zones: Sequence[str],
        maps: Sequence[PointMap],
        conduits: Sequence[Conduit] = CONDUITS,
    ) -> None:
        """Create the network of a facility with *zones* and protocol *maps*."""
        self._kernel, self._conduits = kernel, tuple(conduits)
        self.zones = tuple(zones)
        self._readable: set[tuple[str, str, str, str, int | str]] = set()
        self._writable: set[tuple[str, str, str, str, int | str]] = set()
        self._devices: set[tuple[str, str, str]] = set()
        for m in maps:
            key = (m.zone, m.device, m.protocol, m.object_type, m.address)
            self._readable.add(key)
            self._devices.add((m.zone, m.device, m.protocol))
            if m.writable:
                self._writable.add(key)
        self.violations = AppendOnlyLog(kernel, "net-violations")

    def _decide(self, r: Request) -> Answer:
        for zone in (r.source_zone, r.destination_zone):
            if zone not in self.zones:
                return Answer(False, "", f"no such zone: {zone}")
        if r.source_zone == r.destination_zone:
            return Answer(True, "", "inside one zone: the zone boundary does not apply")
        candidates = conduits_between(r.source_zone, r.destination_zone, self._conduits)
        if not candidates:
            return Answer(False, "", "no conduit joins these zones in this direction")
        refusal = Answer(False, candidates[0].conduit_id, "")
        for conduit in candidates:
            answer = self._through(conduit, r)
            if answer.allowed:
                return answer
            refusal = answer
        return refusal

    def _through(self, c: Conduit, r: Request) -> Answer:
        def no(rule: str) -> Answer:
            return Answer(False, c.conduit_id, rule)

        if r.protocol not in c.protocols:
            return no(f"{c.conduit_id} does not carry {r.protocol}")
        if c.initiator_host and r.source_host != c.initiator_host:
            return no(f"{c.conduit_id} is opened by {c.initiator_host} only")
        if c.responder_host and r.destination_host != c.responder_host:
            return no(f"{c.conduit_id} reaches {c.responder_host} only")
        if c.read_only and r.operation == WRITE:
            return no(f"{c.conduit_id} is one-way: nothing is written through it")
        if c.conduit_id == "C7" and c.initiator_host and not r.permit:
            return no("C7 needs a work permit for the session")
        if c.conduit_id != "C1":
            return Answer(True, c.conduit_id, c.rule)
        if r.source_host not in SUPERVISORY_READERS:
            return no(f"C1: {r.source_host or 'this host'} is not on the allowlist")
        if (r.destination_zone, r.destination_host, r.protocol) not in self._devices:
            return no(f"C1: no {r.protocol} device {r.destination_host} in {r.destination_zone}")
        if r.protocol == "mms":
            # Into a relay the allowlist is by client, relay and service class.
            if r.operation in MMS_PASSED:
                return Answer(True, "C1", c.rule)
            return no(f"C1: MMS {r.operation} is dropped: read and report only")
        if r.operation == CONNECT:
            return Answer(True, "C1", c.rule)
        key = (r.destination_zone, r.destination_host, r.protocol, r.object_type, r.address)
        if key not in self._readable:
            return no(f"C1: {r.object_type} {r.address} is not on the allowlist")
        if r.operation == READ:
            return Answer(True, "C1", c.rule)
        if r.source_host != COMMAND_SERVICE:
            return no("C1: writes come from the command service only")
        if key not in self._writable:
            return no(f"C1: {r.object_type} {r.address} is read-only")
        return Answer(True, "C1", c.rule)

    def request(self, request: Request) -> Answer:
        """Decide *request*. A refusal is logged and published before this returns."""
        answer = self._decide(request)
        if not answer.allowed:
            entry: dict[str, JsonValue] = {
                "source_zone": request.source_zone, "source_host": request.source_host,
                "destination_zone": request.destination_zone,
                "destination": request.destination_host, "protocol": request.protocol,
                "operation": request.operation, "object_type": request.object_type,
                "address": request.address, "conduit": answer.conduit, "rule": answer.rule,
            }  # fmt: skip
            self.violations.append("violation", **entry)
            self._kernel.events.publish("net.violation", entry)
        return answer


def build_network(kernel: Kernel, plant: Plant, points: PointDatabase) -> VirtualNetwork:
    """Build the virtual network of *plant* from its zones and its protocol maps."""
    return VirtualNetwork(kernel, zone_instances(plant), protocol_maps(points))
