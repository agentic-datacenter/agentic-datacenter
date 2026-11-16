"""Protocol maps: where each point is found on each protocol (SDD 8.1, 8.2).

The maps are generated from the point database, so a protocol server and a
conduit allowlist built from them cannot drift from the points.

What is and is not mapped follows ADR 0010:

- A module in ``Z0-PROT`` has no map at all. Protection and life safety leave
  through hardwired contacts only.
- A tier ``T0`` point that is a command or a setting has no map anywhere.
- A tier ``T0`` point that is a status in a controller zone is mapped
  read-only, because a status cannot be written on any tier.
- Only tier ``T2`` and ``T3`` commands and settings are mapped writable.
"""

from __future__ import annotations

from dataclasses import dataclass

from agentic_datacenter.net.zones import PROT
from agentic_datacenter.supervisory.points import PointDatabase

#: Southbound protocol of each device class (SDD 8.2), by module id.
DEVICE_PROTOCOLS: dict[str, tuple[str, ...]] = {
    "electrical.utility": ("modbus",),
    "electrical.mv_switchgear": ("mms",),
    "electrical.power_train": ("modbus",),
    "electrical.genset": ("modbus",),
    "electrical.ups": ("snmp", "modbus"),
    "electrical.it_load": ("modbus",),
    "cooling.chw_plant": ("bacnet",),
    "cooling.pump_station": ("modbus",),
    "cooling.tes": ("modbus",),
    "cooling.pod": ("bacnet", "modbus"),
    "cooling.eroom": ("bacnet",),
    "cooling.weather": ("modbus",),
    "fuel": ("modbus",),
}
#: A fictitious enterprise arc; the simulator implements no vendor's MIB.
SNMP_BASE = "1.3.6.1.4.1.99999"
_WRITABLE_KINDS = ("analog_setting", "binary_cmd")
_MODBUS_TABLE = {
    "binary_in": ("discrete_input", 10001, 1),
    "binary_cmd": ("coil", 1, 1),
    "analog_in": ("input_register", 30001, 2),
    "counter": ("input_register", 30001, 2),
    "enum_status": ("input_register", 30001, 1),
    "analog_setting": ("holding_register", 40001, 2),
}
_BACNET_OBJECT = {
    "binary_in": "binary-input",
    "binary_cmd": "binary-value",
    "analog_in": "analog-input",
    "counter": "analog-input",
    "enum_status": "multi-state-value",
    "analog_setting": "analog-value",
}


@dataclass(frozen=True)
class PointMap:
    """One point on one protocol.

    ``address`` is a register number (Modbus), an object instance (BACnet), an
    object identifier (SNMP) or a node id (OPC UA and MMS). For MMS the device
    is the protection relay, for example ``IED-FDR-A``.
    """

    tag: str
    protocol: str
    zone: str
    device: str
    device_number: int
    object_type: str
    address: int | str
    writable: bool


def _mapped(zone: str, tier: str, kind: str) -> bool:
    if zone == PROT:
        return False
    return not (tier == "T0" and kind in _WRITABLE_KINDS)


def relay_of(point: str, device_points: list[str]) -> str:
    """Return the tag of the protection relay that serves *point* of an MV switchboard.

    The switchboard names its points ``<breaker>_<what>`` and ``bus_<what>``; a
    breaker is recognised by its ``<breaker>_brk_closed`` point. The relay of
    breaker ``fdr_a`` is ``IED-FDR-A``; everything else belongs to ``IED-BUS``
    (SDD 8.5).
    """
    breakers = [p.removesuffix("_brk_closed") for p in device_points if p.endswith("_brk_closed")]
    owner = max((b for b in breakers if point.startswith(b + "_")), key=len, default="bus")
    return "IED-" + owner.upper().replace("_", "-")


def protocol_maps(points: PointDatabase) -> list[PointMap]:
    """Return every protocol map of the facility, in a fixed order."""
    devices: dict[str, list[str]] = {}
    for tag in points.tags():
        devices.setdefault(tag.rpartition(".")[0], []).append(tag)
    out: list[PointMap] = []
    for number, device in enumerate(sorted(devices), start=1):
        module_id = device.split("[", 1)[0]
        protocols = DEVICE_PROTOCOLS.get(module_id, ())
        counters: dict[tuple[str, str], int] = {}
        for index, tag in enumerate(sorted(devices[device]), start=1):
            record = points.read(tag)
            if not protocols or not _mapped(record.zone, record.tier, record.kind):
                continue
            can_write = record.tier in ("T2", "T3") and (
                record.kind in _WRITABLE_KINDS or record.kind == "enum_status"
            )
            for protocol in protocols:
                # A second protocol on a device is a read-only view for collection.
                writable = can_write and protocol == protocols[0]
                if protocol == "modbus":
                    kind = record.kind
                    if kind == "enum_status" and writable:
                        kind = "analog_setting"
                    table, base, width = _MODBUS_TABLE[kind]
                    offset = counters.get((protocol, table), 0)
                    counters[(protocol, table)] = offset + width
                    address: int | str = base + offset
                    object_type = table
                elif protocol == "bacnet":
                    object_type = _BACNET_OBJECT[record.kind]
                    address = counters.get((protocol, object_type), 0) + 1
                    counters[(protocol, object_type)] = int(address)
                elif protocol == "snmp":
                    object_type, address = "scalar", f"{SNMP_BASE}.{number}.{index}.0"
                else:
                    # One MMS server per relay, not per switchboard. Which data
                    # attribute serves the point is the IEC 61850 package's to say.
                    names = [t.rpartition(".")[2] for t in devices[device]]
                    relay = relay_of(tag.rpartition(".")[2], names)
                    out.append(
                        PointMap(tag, protocol, record.zone, relay, number, "data-attribute",
                                 f"{device}/{tag.rpartition('.')[2]}", False)
                    )  # fmt: skip
                    continue
                out.append(
                    PointMap(tag, protocol, record.zone, device, number, object_type, address,
                             writable)
                )  # fmt: skip
            out.append(
                PointMap(tag, "opcua", "Z2-SUP", "opcua-server", 0, "variable", f"ns=2;s={tag}",
                         False)
            )  # fmt: skip
    return out
