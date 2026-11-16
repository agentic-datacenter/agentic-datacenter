"""ADC-PRO-001 for BACnet/IP: the server is a view of the point database (ADR 0013)."""

import asyncio
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import pytest
from bacpypes3.apdu import ErrorRejectAbortNack, WritePropertyRequest
from bacpypes3.app import Application
from bacpypes3.constructeddata import Any as AnyValue
from bacpypes3.ipv4.link import NormalLinkLayer
from bacpypes3.local.device import DeviceObject
from bacpypes3.pdu import Address, IPv4Address
from bacpypes3.primitivedata import CharacterString, ObjectIdentifier

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.net.bacnet import CONTROLLER_NETWORK, BacnetError, BacnetServer, BacnetView
from agentic_datacenter.net.guard import ExternalAddressError
from agentic_datacenter.net.maps import PointMap, protocol_maps
from agentic_datacenter.net.zones import PROT
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[2]
CHWS_SP = "cooling.chw_plant[CHW].chws_sp_c"
CHWS = "cooling.chw_plant[CHW].chws_c"
CH3_ENABLE = "cooling.chw_plant[CHW].ch3_enable"
CH1_STATE = "cooling.chw_plant[CHW].ch1_state"
LEAD = "cooling.chw_plant[CHW].lead_chiller"
AHU_RUNNING = "cooling.pod[07].ahu_running"
UNITS = {
    "degC": "degrees-celsius",
    "kW": "kilowatts",
    "%": "percent",
    "Pa": "pascals",
    "min": "minutes",
    "": "no-units",
}
ANALOG = ("analog-input", "analog-value")
NO_FLAGS = (False, False, False, False)
FAULT = (False, True, False, False)


class Client:
    """A BACnet client on loopback that is told where the controller network is."""

    def __init__(self, port: int) -> None:
        self.loop = asyncio.new_event_loop()
        self.app, self.link = self.loop.run_until_complete(self._open(port))

    @staticmethod
    async def _open(port: int) -> tuple[Any, Any]:
        device = DeviceObject(
            objectIdentifier=("device", 4_000_001), objectName="test client", vendorIdentifier=999
        )
        app = Application.from_object_list([device])
        address = IPv4Address("127.0.0.1/32:0")
        link = NormalLinkLayer(address)
        app.nsap.bind(link, address=address)
        router = IPv4Address(f"127.0.0.1:{port}")
        await app.nsap.router_info_cache.update_path_info(None, router, {CONTROLLER_NETWORK})
        return app, link

    def run(self, call: Any) -> Any:
        return self.loop.run_until_complete(asyncio.wait_for(call, 5))

    def read(self, device: int, obj: str, prop: str, index: int | None = None) -> Any:
        address = Address(f"{CONTROLLER_NETWORK}:{device}")
        return self.run(self.app.read_property(address, obj, prop, index))

    def write(self, device: int, obj: str, prop: str, value: Any) -> Any:
        address = Address(f"{CONTROLLER_NETWORK}:{device}")
        return self.run(self.app.write_property(address, obj, prop, value))

    def who_is(self) -> list[int]:
        async def ask() -> Any:
            return await self.app.who_is(address=Address(f"{CONTROLLER_NETWORK}:*"), timeout=1)

        return sorted(int(answer.iAmDeviceIdentifier[1]) for answer in self.run(ask()))

    def write_text(self, device: int, obj: str, prop: str, text: str) -> Any:
        """Write a character string, whatever datatype the property has."""

        async def ask() -> Any:
            request = WritePropertyRequest(
                objectIdentifier=ObjectIdentifier(obj),
                propertyIdentifier=prop,
                propertyValue=AnyValue(CharacterString(text)),
                destination=Address(f"{CONTROLLER_NETWORK}:{device}"),
            )
            return await self.app.request(request)

        return self.run(ask())

    def close(self) -> None:
        self.link.close()
        self.app.close()
        self.loop.run_until_complete(asyncio.sleep(0.05))
        self.loop.close()


@pytest.fixture(scope="module")
def site() -> Iterator[tuple[Kernel, Any, PointDatabase, list[PointMap], BacnetServer, Client]]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    kernel.run_for(5000)
    maps = [m for m in protocol_maps(points) if m.protocol == "bacnet"]
    server = BacnetServer(BacnetView(kernel, points, maps))
    port = server.start("127.0.0.1", 0)
    client = Client(port)
    yield kernel, plant, points, maps, server, client
    client.close()
    server.stop()


def find(maps: list[PointMap], tag: str) -> PointMap:
    return next(m for m in maps if m.tag == tag)


def name(m: PointMap) -> str:
    return f"{m.object_type},{m.address}"


def flags(value: Any) -> tuple[bool, ...]:
    return tuple(bool(bit) for bit in value)


def refusal(call: Callable[[], Any]) -> tuple[str, str]:
    with pytest.raises(ErrorRejectAbortNack) as caught:
        call()
    return str(caught.value.errorClass), str(caught.value.errorCode)


def view_refusal(call: Callable[[], Any]) -> tuple[str, str]:
    with pytest.raises(BacnetError) as caught:
        call()
    return caught.value.error_class, caught.value.error_code


@pytest.mark.req("ADC-PRO-001")
def test_every_mapped_point_reads_as_the_point_database_holds_it(site: Any) -> None:
    _, _, points, maps, _, client = site
    assert len(maps) > 300
    for m in maps:
        record = points.read(m.tag)
        decl = points.declaration(m.tag)
        raw = client.read(m.device_number, name(m), "present-value")
        if m.object_type in ANALOG:
            assert float(raw) == pytest.approx(float(record.value), rel=1e-6, abs=1e-6), m.tag
            units = client.read(m.device_number, name(m), "units")
            assert str(units) == UNITS[record.unit], m.tag
        elif m.object_type == "multi-state-value":
            assert (decl.values or ())[int(raw) - 1] == record.value, m.tag
        else:
            assert (str(raw) == "active") is record.value, m.tag
        assert flags(client.read(m.device_number, name(m), "status-flags")) == NO_FLAGS, m.tag
        assert str(client.read(m.device_number, name(m), "object-name")) == m.tag


@pytest.mark.req("ADC-PRO-001")
def test_the_view_answers_without_a_socket_as_the_server_does_with_one(site: Any) -> None:
    _, _, points, maps, server, client = site
    view = server.view
    for tag in (CHWS, CHWS_SP, CH3_ENABLE, CH1_STATE, AHU_RUNNING):
        m = find(maps, tag)
        record = points.read(tag)
        value = view.read_property(m.device_number, m.object_type, int(m.address), "present-value")
        wire = client.read(m.device_number, name(m), "present-value")
        if record.kind == "enum_status":
            assert value == int(wire) == points.declaration(tag).values.index(record.value) + 1
        elif record.kind.startswith("binary"):
            assert value is record.value and (str(wire) == "active") is value
        else:
            assert value == pytest.approx(float(record.value))
            assert float(wire) == pytest.approx(value, rel=1e-6)
        read = view.read_property
        assert read(m.device_number, m.object_type, int(m.address), "object-name") == tag
        assert read(m.device_number, m.object_type, int(m.address), "status-flags") == NO_FLAGS
        assert read(m.device_number, m.object_type, int(m.address), "description") == (
            record.description
        )


@pytest.mark.req("ADC-PRO-001")
def test_an_enumerated_status_carries_the_names_of_its_states(site: Any) -> None:
    _, _, points, maps, server, client = site
    m = find(maps, CH1_STATE)
    states = list(points.declaration(CH1_STATE).values)
    assert int(client.read(m.device_number, name(m), "number-of-states")) == len(states)
    assert [str(s) for s in client.read(m.device_number, name(m), "state-text")] == states
    assert int(client.read(m.device_number, name(m), "state-text", 0)) == len(states)
    assert str(client.read(m.device_number, name(m), "state-text", 2)) == states[1]
    call = lambda: client.read(m.device_number, name(m), "state-text", 9)  # noqa: E731
    assert refusal(call) == ("property", "invalid-array-index")
    call = lambda: client.read(m.device_number, name(m), "present-value", 1)  # noqa: E731
    assert refusal(call) == ("property", "property-is-not-an-array")
    assert server.view.read_property(
        m.device_number, m.object_type, int(m.address), "state-text"
    ) == (states)


@pytest.mark.req("ADC-PRO-001")
def test_a_value_that_changes_in_the_plant_changes_on_the_wire(site: Any) -> None:
    kernel, plant, points, maps, _, client = site
    m = find(maps, AHU_RUNNING)
    before = points.read(AHU_RUNNING).value
    assert float(client.read(m.device_number, name(m), "present-value")) == before
    plant.module("cooling.pod", "07").inject("ahu_fail", unit=1)
    kernel.run_for(1000)
    assert points.read(AHU_RUNNING).value == before - 1
    assert float(client.read(m.device_number, name(m), "present-value")) == before - 1
    plant.module("cooling.pod", "07").inject("ahu_restore", unit=1)
    kernel.run_for(1000)


@pytest.mark.req("ADC-PRO-001")
def test_every_controller_is_a_device_that_lists_its_objects(site: Any) -> None:
    _, _, _, maps, server, client = site
    devices = {m.device_number: m.device for m in maps}
    assert dict(server.view.devices()) == devices
    assert client.who_is() == sorted(devices)
    for number, device in devices.items():
        assert str(client.read(number, f"device,{number}", "object-name")) == device
        listed = client.read(number, f"device,{number}", "object-list")
        expected = {(m.object_type, int(m.address)) for m in maps if m.device_number == number}
        assert {(str(kind), int(instance)) for kind, instance in listed} == expected | {
            ("device", number)
        }
        assert set(server.view.objects(number)) == expected


@pytest.mark.req("ADC-PRO-001")
def test_unknown_object_and_unknown_property_get_the_right_error(site: Any) -> None:
    _, _, _, maps, server, client = site
    m = find(maps, CHWS)
    unit = m.device_number
    read, view = client.read, server.view
    assert refusal(lambda: read(unit, "analog-input,900", "present-value")) == (
        "object",
        "unknown-object",
    )
    assert refusal(lambda: read(unit, "binary-output,1", "present-value")) == (
        "object",
        "unknown-object",
    )
    assert refusal(lambda: read(unit, name(m), "priority-array")) == (
        "property",
        "unknown-property",
    )
    assert refusal(lambda: read(unit, name(find(maps, CH3_ENABLE)), "units")) == (
        "property",
        "unknown-property",
    )
    assert refusal(lambda: read(unit, f"device,{unit}", "local-time")) == (
        "property",
        "unknown-property",
    )
    assert view_refusal(lambda: view.read_property(unit, "analog-input", 900, "present-value")) == (
        "object",
        "unknown-object",
    )
    assert view_refusal(
        lambda: view.read_property(unit, m.object_type, int(m.address), "priority-array")
    ) == ("property", "unknown-property")


@pytest.mark.req("ADC-PRO-001")
def test_a_service_the_controller_does_not_serve_is_rejected(site: Any) -> None:
    _, _, _, maps, _, client = site
    m = find(maps, CHWS)
    address = Address(f"{CONTROLLER_NETWORK}:{m.device_number}")
    with pytest.raises(ErrorRejectAbortNack) as caught:
        client.run(client.app.read_property_multiple(address, [name(m), ["present-value"]]))
    assert str(caught.value.apduAbortRejectReason) == "unrecognized-service"


@pytest.mark.req("ADC-PRO-001")
def test_a_value_the_point_does_not_allow_is_refused(site: Any) -> None:
    _, _, points, maps, server, client = site
    setpoint, lead = find(maps, CHWS_SP), find(maps, LEAD)
    unit = setpoint.device_number
    before = points.read(CHWS_SP).value, points.read(LEAD).value
    out_of_range = ("property", "value-out-of-range")
    assert refusal(lambda: client.write(unit, name(setpoint), "present-value", 99.0)) == (
        out_of_range
    )
    assert refusal(lambda: client.write(unit, name(lead), "present-value", 9)) == out_of_range
    assert refusal(lambda: client.write(unit, name(lead), "present-value", 0)) == out_of_range
    assert refusal(lambda: client.write_text(unit, name(setpoint), "present-value", "warm")) == (
        "property",
        "invalid-data-type",
    )
    view = server.view
    assert view_refusal(
        lambda: view.write_property(unit, "analog-value", int(setpoint.address), "present-value", 1)
    ) == ("property", "value-out-of-range")
    assert view_refusal(
        lambda: view.write_property(
            unit, "analog-value", int(setpoint.address), "present-value", "warm"
        )
    ) == ("property", "invalid-data-type")
    assert view_refusal(
        lambda: view.write_property(
            unit, "multi-state-value", int(lead.address), "present-value", 2.5
        )
    ) == ("property", "invalid-data-type")
    assert (points.read(CHWS_SP).value, points.read(LEAD).value) == before, "nothing was written"


@pytest.mark.req("ADC-PRO-001")
def test_a_writable_point_is_written_and_read_back(site: Any) -> None:
    kernel, plant, points, maps, _, client = site
    setpoint, enable, lead = find(maps, CHWS_SP), find(maps, CH3_ENABLE), find(maps, LEAD)
    assert setpoint.writable and enable.writable and lead.writable
    unit = setpoint.device_number
    before = points.read(CHWS_SP).value, points.read(CH3_ENABLE).value, points.read(LEAD).value
    client.write(unit, name(setpoint), "present-value", 19.5)
    assert points.read(CHWS_SP).value == 19.5
    assert float(client.read(unit, name(setpoint), "present-value")) == 19.5
    client.write(unit, name(enable), "present-value", "inactive")
    assert points.read(CH3_ENABLE).value is False
    client.write(unit, name(lead), "present-value", 2)
    assert points.read(LEAD).value == "2"
    assert int(client.read(unit, name(lead), "present-value")) == 2
    kernel.run_for(2000)
    assert plant.module("cooling.chw_plant", "CHW").io["chws_sp_c"] == 19.5
    client.write(unit, name(setpoint), "present-value", float(before[0]))
    client.write(unit, name(enable), "present-value", "active" if before[1] else "inactive")
    client.write(unit, name(lead), "present-value", int(before[2]))
    kernel.run_for(2000)
    assert (points.read(CHWS_SP).value, points.read(CH3_ENABLE).value, points.read(LEAD).value) == (
        before
    )


@pytest.mark.req("ADC-PRO-001")
def test_a_write_to_a_read_only_point_is_refused_and_recorded(site: Any) -> None:
    kernel, _, points, maps, server, client = site
    status, setpoint = find(maps, CHWS), find(maps, CHWS_SP)
    assert not status.writable
    before = points.read(CHWS).value
    seen: list[Any] = []
    kernel.events.subscribe("net.device_violation", seen.append)
    denied = ("property", "write-access-denied")
    unit = status.device_number
    assert refusal(lambda: client.write(unit, name(status), "present-value", 1.0)) == denied
    assert points.read(CHWS).value == before
    violations = server.view.violations()
    assert violations and violations[-1]["tag"] == CHWS
    assert violations[-1]["device"] == status.device and violations[-1]["unit"] == unit
    assert violations[-1]["function"] == "write-property"
    assert violations[-1]["address"] == name(status)
    assert str(violations[-1]["source"]).startswith("127.0.0.1:")
    assert seen and seen[-1].payload["tag"] == CHWS
    # The name of a writable object is not writable either.
    assert refusal(lambda: client.write(unit, name(setpoint), "object-name", "mine")) == denied
    assert server.view.violations()[-1]["tag"] == CHWS_SP
    # Nor is there anything to write where there is no object.
    assert refusal(lambda: client.write(unit, "analog-value,900", "present-value", 1.0)) == (
        "object",
        "unknown-object",
    )
    assert server.view.violations()[-1]["tag"] == ""
    assert len(seen) == 3


@pytest.mark.req("ADC-PRO-001")
def test_the_quality_of_a_point_is_its_fault_flag(site: Any) -> None:
    kernel, _, points, maps, server, client = site
    m = find(maps, CHWS)
    where = (m.device_number, m.object_type, int(m.address))
    assert server.view.read_property(*where, "reliability") == "no-fault-detected"
    points.set_link(False)
    try:
        kernel.run_for(4000)
        assert points.read(CHWS).quality == "stale"
        assert server.view.read_property(*where, "status-flags") == FAULT
        assert server.view.read_property(*where, "reliability") == "communication-failure"
        assert server.view.read_property(*where, "out-of-service") is False
        assert flags(client.read(m.device_number, name(m), "status-flags")) == FAULT
        assert str(client.read(m.device_number, name(m), "reliability")) == "communication-failure"
        held = float(client.read(m.device_number, name(m), "present-value"))
        assert held == pytest.approx(float(points.read(CHWS).value), rel=1e-6)
    finally:
        points.set_link(True)
    kernel.run_for(1000)
    assert flags(client.read(m.device_number, name(m), "status-flags")) == NO_FLAGS


def test_protection_and_life_safety_are_not_on_the_wire(site: Any) -> None:
    _, _, points, maps, server, _ = site
    view = server.view
    served = {
        view.read_property(number, kind, instance, "object-name")
        for number, _ in view.devices()
        for kind, instance in view.objects(number)
    }
    assert served == {m.tag for m in maps}
    assert not [tag for tag in served if points.read(tag).zone == PROT]
    assert not [t for t in served if t.startswith(("life_safety[", "security["))]
    for tag in served:
        record, m = points.read(tag), find(maps, tag)
        assert not (record.tier == "T0" and m.writable), tag
        if record.tier == "T0":
            where = (m.device_number, m.object_type, int(m.address), "present-value")
            assert view_refusal(lambda where=where: view.write_property(*where, 1.0)) == (
                "property",
                "write-access-denied",
            )


@pytest.mark.req("ADC-SAF-001")
def test_the_server_refuses_to_bind_outside_the_simulators_own_networks(site: Any) -> None:
    _, _, _, _, server, _ = site
    other = BacnetServer(server.view)
    with pytest.raises(ExternalAddressError):
        other.start("0.0.0.0", 0)  # noqa: S104
    with pytest.raises(ExternalAddressError):
        other.start("192.0.2.10", 47808)


def test_a_stopped_server_releases_its_port_and_can_start_again(site: Any) -> None:
    _, _, _, maps, server, _ = site
    other = BacnetServer(server.view)
    port = other.start("127.0.0.1", 0)
    client = Client(port)
    m = find(maps, CHWS)
    assert str(client.read(m.device_number, name(m), "object-name")) == CHWS
    client.close()
    other.stop()
    assert other.start("127.0.0.1", port) == port
    other.stop()
