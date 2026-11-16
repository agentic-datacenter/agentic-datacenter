"""The BACnet/IP view of the point database (SDD 8, ADR 0013).

One BACnet device per mapped controller, with one object per mapped point.
A read is answered with what the point database holds at that moment; a
write is accepted only at the present value of an object the map marks
writable and only with a value the point's declaration allows. Everything
else gets the error a field controller would give.

:class:`BacnetView` knows nothing of the protocol library: it takes and
returns plain values and names properties, object types, error classes and
error codes as the standard spells them (``present-value``, ``analog-input``,
``unknown-object``). :class:`BacnetServer` puts it on the wire: one BACnet
router on one UDP port, and every controller a device on a virtual network
behind it, at the address that is its device number.

Encoding: an analog value and a counter are a REAL; a binary point is active
or inactive; an enumerated status is the position of its state, counted from
one. A quality other than ``good`` sets the fault flag.

The server answers at once: the response latency of section 8.4 is not
modelled here.
"""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Callable, Sequence
from typing import Any

from bacpypes3.apdu import (
    ConfirmedRequestPDU,
    ReadPropertyACK,
    ReadPropertyRequest,
    RejectPDU,
    SimpleAckPDU,
    WhoIsRequest,
    WritePropertyRequest,
)
from bacpypes3.app import Application
from bacpypes3.basetypes import (
    BinaryPV,
    EngineeringUnits,
    EventState,
    Polarity,
    Reliability,
    ServicesSupported,
    StatusFlags,
)
from bacpypes3.comm import bind
from bacpypes3.constructeddata import ArrayOf
from bacpypes3.errors import ExecutionError
from bacpypes3.ipv4.link import NormalLinkLayer
from bacpypes3.local.device import DeviceObject
from bacpypes3.netservice import NetworkServiceAccessPoint, NetworkServiceElement
from bacpypes3.pdu import IPv4Address, LocalStation
from bacpypes3.primitivedata import (
    Boolean,
    CharacterString,
    ObjectIdentifier,
    ObjectType,
    Real,
    Unsigned,
)
from bacpypes3.vlan import VirtualNetwork
from bacpypes3.vlan.link import VirtualLinkLayer

from agentic_datacenter.core.io import PointValue
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.net.guard import check_bind
from agentic_datacenter.net.maps import PointMap
from agentic_datacenter.supervisory.points import PointDatabase

#: The network the router's UDP port is on, and the one the controllers are on.
ROUTER_NETWORK = 1
CONTROLLER_NETWORK = 2
#: The value the library's samples use. No vendor's proprietary objects are implemented.
VENDOR_IDENTIFIER = 999
#: BACnet engineering units for the unit strings the plant modules use.
UNITS = {
    "degC": "degrees-celsius",
    "kW": "kilowatts",
    "kWh": "kilowatt-hours",
    "%": "percent",
    "Pa": "pascals",
    "kPa": "kilopascals",
    "A": "amperes",
    "s": "seconds",
    "min": "minutes",
    "h": "hours",
    "l": "liters",
    "l/h": "liters-per-hour",
    "kg/s": "kilograms-per-second",
}
_ANALOG = ("analog-input", "analog-value")
_BINARY = ("binary-input", "binary-value")
_RELIABILITY = {"good": "no-fault-detected", "stale": "communication-failure"}
_ANY_DEVICE = 4194303

type BacnetValue = (
    bool
    | int
    | float
    | str
    | tuple[bool, ...]
    | tuple[str, int]
    | list[str]
    | list[tuple[str, int]]
)


class BacnetError(Exception):
    """What a controller answers instead of a value: an error class and an error code."""

    def __init__(self, error_class: str, error_code: str) -> None:
        """Keep the class and code, spelled as the standard spells them."""
        super().__init__(f"{error_class}: {error_code}")
        self.error_class, self.error_code = error_class, error_code


class BacnetView:
    """Every BACnet device of the facility, as views of the point database."""

    def __init__(self, kernel: Kernel, points: PointDatabase, maps: Sequence[PointMap]) -> None:
        """Build the object tables from the BACnet *maps*."""
        self._kernel, self._points = kernel, points
        self.lock = threading.Lock()
        self._violations: list[dict[str, JsonValue]] = []
        #: device number -> (object type, instance) -> map
        self._objects: dict[int, dict[tuple[str, int], PointMap]] = {}
        self._names: dict[int, str] = {}
        for m in maps:
            if m.protocol != "bacnet":
                continue
            self._objects.setdefault(m.device_number, {})[m.object_type, int(m.address)] = m
            self._names[m.device_number] = m.device

    # -- what is there -------------------------------------------------------------------------

    def devices(self) -> list[tuple[int, str]]:
        """Return the device instance and name of every controller."""
        return sorted(self._names.items())

    def objects(self, device: int) -> list[tuple[str, int]]:
        """Return object type and instance of every point object of *device*.

        Raises:
            KeyError: If there is no such device. On the wire it does not answer.
        """
        return sorted(self._objects[device])

    def _properties(self, m: PointMap) -> dict[str, BacnetValue]:
        record = self._points.read(m.tag)
        decl = self._points.declaration(m.tag)
        value: BacnetValue
        if m.object_type in _ANALOG:
            value = float(record.value)
        elif m.object_type in _BINARY:
            value = bool(record.value)
        else:
            value = (decl.values or ()).index(str(record.value)) + 1
        out: dict[str, BacnetValue] = {
            "object-identifier": (m.object_type, int(m.address)),
            "object-name": m.tag,
            "object-type": m.object_type,
            "description": record.description,
            "present-value": value,
            "status-flags": (False, record.quality != "good", False, False),
            "event-state": "normal",
            "reliability": _RELIABILITY.get(record.quality, "unreliable-other"),
            "out-of-service": False,
        }
        if m.object_type in _ANALOG:
            out["units"] = UNITS.get(record.unit, "no-units")
        elif m.object_type == "binary-input":
            out["polarity"] = "normal"
        elif m.object_type not in _BINARY:
            out["number-of-states"] = len(decl.values or ())
            out["state-text"] = list(decl.values or ())
        return out

    def _device_properties(self, device: int) -> dict[str, BacnetValue]:
        return {
            "object-identifier": ("device", device),
            "object-name": self._names[device],
            "object-type": "device",
            "object-list": [("device", device), *self.objects(device)],
        }

    # -- the two services ----------------------------------------------------------------------

    def read_property(
        self, device: int, object_type: str, instance: int, prop: str, index: int | None = None
    ) -> BacnetValue:
        """Return property *prop* of an object of *device*.

        Of the device object the view knows only its identity and its object
        list. With *index*, return the length of an array property (0) or
        one of its elements (counted from one).

        Raises:
            BacnetError: With the class and code the controller answers.
            KeyError: If there is no such device.
        """
        if object_type == "device" and instance == device:
            properties = self._device_properties(device)
        else:
            m = self._objects[device].get((object_type, instance))
            if m is None:
                raise BacnetError("object", "unknown-object")
            properties = self._properties(m)
        if prop not in properties:
            raise BacnetError("property", "unknown-property")
        value = properties[prop]
        if index is None:
            return value
        if not isinstance(value, list):
            raise BacnetError("property", "property-is-not-an-array")
        if index == 0:
            return len(value)
        if not 1 <= index <= len(value):
            raise BacnetError("property", "invalid-array-index")
        return value[index - 1]

    def _refuse(self, device: int, address: str, tag: str, why: str, source: str) -> None:
        entry: dict[str, JsonValue] = {
            "time_ms": self._kernel.clock.now_ms, "device": self._names[device], "unit": device,
            "function": "write-property", "address": address, "tag": tag, "reason": why,
            "source": source,
        }  # fmt: skip
        self._violations.append(entry)
        self._kernel.events.publish("net.device_violation", entry)

    def write_property(
        self,
        device: int,
        object_type: str,
        instance: int,
        prop: str,
        value: object,
        index: int | None = None,
        source: str = "",
    ) -> None:
        """Write *value* to property *prop* of an object of *device*.

        Only the present value of an object the map marks writable can be
        written: a number for an analog value, a bool for a binary value, the
        position of the state for a multi-state value. A refused write to a
        read-only or missing object is a device violation event, with the
        address *source* of whoever asked.

        Raises:
            BacnetError: With the class and code the controller answers.
            KeyError: If there is no such device.
        """
        address = f"{object_type},{instance}"
        if object_type == "device" and instance == device:
            if prop not in self._device_properties(device):
                raise BacnetError("property", "unknown-property")
            self._refuse(device, address, "", "the device object is read-only", source)
            raise BacnetError("property", "write-access-denied")
        m = self._objects[device].get((object_type, instance))
        if m is None:
            self._refuse(device, address, "", "no object with this identifier", source)
            raise BacnetError("object", "unknown-object")
        if prop not in self._properties(m):
            raise BacnetError("property", "unknown-property")
        if prop != "present-value" or not m.writable:
            why = "the point is read-only" if not m.writable else "the property is read-only"
            self._refuse(device, address, m.tag, why, source)
            raise BacnetError("property", "write-access-denied")
        if index is not None:
            raise BacnetError("property", "property-is-not-an-array")
        decl = self._points.declaration(m.tag)
        number = isinstance(value, int | float) and not isinstance(value, bool)
        point_value: PointValue
        if object_type in _ANALOG and number:
            point_value = float(value)  # type: ignore[arg-type]
        elif object_type in _BINARY and isinstance(value, bool):
            point_value = value
        elif object_type == "multi-state-value" and number and isinstance(value, int):
            states = decl.values or ()
            if not 1 <= value <= len(states):
                raise BacnetError("property", "value-out-of-range")
            point_value = states[value - 1]
        else:
            raise BacnetError("property", "invalid-data-type")
        if decl.problem_with(point_value) is not None:
            raise BacnetError("property", "value-out-of-range")
        self._points.write_through(m.tag, point_value)

    def violations(self) -> list[dict[str, JsonValue]]:
        """Return every refused write so far."""
        return [dict(entry) for entry in self._violations]


# -- the library side --------------------------------------------------------------------------

_SERVED = (WhoIsRequest, ReadPropertyRequest, WritePropertyRequest)
_SERVICES = ("whoIs", "readProperty", "writeProperty")
#: The library's device object would answer these from the host clock (ADC-KRN-003).
_HOST_CLOCK = ("local-time", "local-date")
_PRESENT_VALUE: dict[str, Any] = {
    "analog-input": Real,
    "analog-value": Real,
    "binary-input": BinaryPV,
    "binary-value": BinaryPV,
    "multi-state-value": Unsigned,
}
_ENCODERS: dict[str, Callable[[Any], Any]] = {
    "object-identifier": ObjectIdentifier,
    "object-name": CharacterString,
    "object-type": ObjectType,
    "description": CharacterString,
    "status-flags": lambda bits: StatusFlags([int(bit) for bit in bits]),
    "event-state": EventState,
    "reliability": Reliability,
    "out-of-service": Boolean,
    "units": EngineeringUnits,
    "polarity": Polarity,
    "number-of-states": Unsigned,
    "state-text": CharacterString,
    "object-list": ObjectIdentifier,
}


def _encode(object_type: str, prop: str, value: BacnetValue, index: int | None) -> Any:
    """Return *value* as the library's type for property *prop*."""
    if prop == "present-value":
        if object_type in _BINARY:
            return BinaryPV(int(bool(value)))
        return _PRESENT_VALUE[object_type](value)
    element = _ENCODERS[prop]
    if isinstance(value, list):
        return ArrayOf(element)([element(item) for item in value])
    return Unsigned(value) if index == 0 else element(value)


def _decode(object_type: str, prop: str, raw: Any) -> object:
    """Return a written value as a plain one, or None if it is of the wrong datatype."""
    wanted = _PRESENT_VALUE.get(object_type)
    if prop != "present-value" or wanted is None:
        return None
    try:
        value = raw.cast_out(wanted)
    except Exception:  # the library has several ways to say "not that type"
        return None
    if wanted is Real:
        return float(value)
    if wanted is BinaryPV:
        return int(value) == 1 if int(value) in (0, 1) else None
    return int(value)


def _source(address: Any) -> str:
    """Return who sent a request: ``ip:port`` for a BACnet/IP station behind the router."""
    raw = getattr(address, "addrAddr", None)
    if isinstance(raw, bytes) and len(raw) == 6:
        return f"{socket.inet_ntoa(raw[:4])}:{int.from_bytes(raw[4:], 'big')}"
    return str(address)


class _Controller(Application):  # type: ignore[misc]
    """One controller: the library's application layer, answering from the view."""

    view: BacnetView
    number: int

    def get_services_supported(self) -> Any:
        """Return the services this controller executes, for its device object."""
        supported = ServicesSupported([])
        for name in _SERVICES:
            supported[getattr(supported, name)] = 1
        return supported

    async def indication(self, apdu: Any) -> None:
        """Serve Who-Is, ReadProperty and WriteProperty; reject every other request."""
        if isinstance(apdu, _SERVED):
            await super().indication(apdu)
        elif isinstance(apdu, ConfirmedRequestPDU):
            await self.response(RejectPDU(reason="unrecognized-service", context=apdu))

    def _target(self, apdu: Any) -> tuple[str, int, str]:
        object_type, instance = str(apdu.objectIdentifier[0]), int(apdu.objectIdentifier[1])
        if object_type == "device" and instance == _ANY_DEVICE:
            instance = self.number
        return object_type, instance, str(apdu.propertyIdentifier)

    async def do_ReadPropertyRequest(self, apdu: Any) -> None:  # noqa: N802 - the library's name
        """Answer a ReadProperty request from the view."""
        object_type, instance, prop = self._target(apdu)
        index = apdu.propertyArrayIndex
        if object_type == "device" and instance == self.number:
            if prop in _HOST_CLOCK:
                raise ExecutionError("property", "unknown-property")
            if prop not in ("object-list", "object-name"):
                # Protocol housekeeping (APDU size, services, vendor) is the library's.
                await super().do_ReadPropertyRequest(apdu)
                return
        try:
            with self.view.lock:
                value = self.view.read_property(self.number, object_type, instance, prop, index)
        except BacnetError as refused:
            raise ExecutionError(refused.error_class, refused.error_code) from None
        answer = ReadPropertyACK(
            objectIdentifier=(object_type, instance),
            propertyIdentifier=apdu.propertyIdentifier,
            propertyArrayIndex=index,
            propertyValue=_encode(object_type, prop, value, index),
            context=apdu,
        )
        await self.response(answer)

    async def do_WritePropertyRequest(self, apdu: Any) -> None:  # noqa: N802 - the library's name
        """Apply or refuse a WriteProperty request through the view."""
        object_type, instance, prop = self._target(apdu)
        value = _decode(object_type, prop, apdu.propertyValue)
        try:
            with self.view.lock:
                self.view.write_property(
                    self.number, object_type, instance, prop, value,
                    index=apdu.propertyArrayIndex, source=_source(apdu.pduSource),
                )  # fmt: skip
        except BacnetError as refused:
            raise ExecutionError(refused.error_class, refused.error_code) from None
        await self.response(SimpleAckPDU(context=apdu))


def _station(number: int) -> Any:
    """Return the address of device *number* on the controller network."""
    return LocalStation(number.to_bytes(max(1, (number.bit_length() + 7) // 8), "big"))


class BacnetServer:
    """Serves a :class:`BacnetView` on a UDP port, from a thread of its own."""

    def __init__(self, view: BacnetView) -> None:
        """Create the server; nothing is bound until :meth:`start`."""
        self.view = view
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._network = ""
        self._link: Any = None
        self._stack: list[Any] = []

    def _build(self, bound: socket.socket) -> None:
        """Wire the router and one application per controller. Needs a running loop."""
        host, port = bound.getsockname()[:2]
        self._network = f"agentic-datacenter-bacnet-{host}:{port}"
        VirtualNetwork(self._network)
        address = IPv4Address(f"{host}/32:{port}")
        router = NetworkServiceAccessPoint()
        element = NetworkServiceElement()
        bind(element, router)
        self._link = NormalLinkLayer(address, bind_socket=bound)
        router.bind(self._link, net=ROUTER_NETWORK, address=address)
        router.bind(VirtualLinkLayer(_station(0), self._network), net=CONTROLLER_NETWORK)
        self._stack = [router, element]
        for number, name in self.view.devices():
            device = DeviceObject(
                objectIdentifier=("device", number),
                objectName=name,
                vendorIdentifier=VENDOR_IDENTIFIER,
                vendorName="Agentic Datacenter",
                modelName=name.split("[", 1)[0],
                description="Simulated controller; not real equipment",
            )
            controller = _Controller.from_object_list([device])
            controller.view, controller.number = self.view, number
            station = _station(number)
            controller.nsap.bind(VirtualLinkLayer(station, self._network), address=station)
            self._stack.append(controller)

    def start(self, host: str, port: int, allow_external: bool = False) -> int:
        """Bind UDP *host*:*port* (0 picks a free port) and serve. Return the port.

        Raises:
            ExternalAddressError: If the address is outside the simulator's own
                networks and *allow_external* is not set (ADC-SAF-001).
        """
        check_bind(host, allow_external=allow_external)
        if self._thread is not None:
            raise RuntimeError("the BACnet server is already running")
        bound = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            bound.bind((host, port))
        except OSError:
            bound.close()
            raise
        bound.setblocking(False)
        port = int(bound.getsockname()[1])
        ready = threading.Event()
        failed: list[BaseException] = []

        def run() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._loop = loop

            async def build() -> None:
                self._build(bound)
                # The library opens its endpoint in a task; serve only once it has.
                for _ in range(1000):
                    if self._link.server.local_transport is not None:
                        return
                    await asyncio.sleep(0)
                raise RuntimeError("the datagram endpoint did not open")

            try:
                loop.run_until_complete(build())
                ready.set()
                loop.run_forever()
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except BaseException as exc:  # noqa: BLE001 - reported to the caller below
                failed.append(exc)
                ready.set()
            finally:
                asyncio.set_event_loop(None)
                loop.close()

        self._thread = threading.Thread(target=run, name="agentic-datacenter-bacnet", daemon=True)
        self._thread.start()
        if not ready.wait(10.0) or failed:
            self._thread.join(10.0)
            self._forget()
            bound.close()
            raise RuntimeError(f"the BACnet server did not start: {failed[0] if failed else ''}")
        return port

    def _forget(self) -> None:
        # The library keeps virtual networks by name for the life of the process.
        VirtualNetwork._networks.pop(self._network, None)
        self._thread = self._loop = self._link = None
        self._stack = []

    def stop(self) -> None:
        """Stop serving and release the port."""
        if self._loop is None or self._thread is None:
            return
        loop, link = self._loop, self._link

        async def close() -> None:
            link.close()
            # One turn of the loop lets the transport close its socket.
            await asyncio.sleep(0)

        asyncio.run_coroutine_threadsafe(close(), loop).result(10.0)
        loop.call_soon_threadsafe(loop.stop)
        self._thread.join(10.0)
        self._forget()
