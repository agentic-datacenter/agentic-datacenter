"""ADC-PRO-001 for Modbus/TCP: the server is a view of the point database (ADR 0012)."""

import struct
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pymodbus.client import ModbusTcpClient

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.net.guard import ExternalAddressError
from agentic_datacenter.net.maps import PointMap, protocol_maps
from agentic_datacenter.net.modbus import ModbusServer, ModbusView, decode
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[2]
TEST_START = "electrical.genset[A].test_start_request"
DP_SP = "cooling.pump_station[PHPS].dp_sp_kpa"
TDEN = "electrical.power_train[A].tden_s"
OFFSET = {"coil": 1, "discrete_input": 10001, "input_register": 30001, "holding_register": 40001}


@pytest.fixture(scope="module")
def site() -> Iterator[tuple[Kernel, Any, PointDatabase, list[PointMap], ModbusServer, Any]]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    kernel.run_for(5000)
    maps = [m for m in protocol_maps(points) if m.protocol == "modbus"]
    server = ModbusServer(ModbusView(kernel, points, maps))
    port = server.start("127.0.0.1", 0)
    client = ModbusTcpClient("127.0.0.1", port=port, timeout=5)
    assert client.connect()
    yield kernel, plant, points, maps, server, client
    client.close()
    server.stop()


def read(client: Any, m: PointMap, count: int) -> Any:
    address = int(m.address) - OFFSET[m.object_type]
    call = {
        "coil": client.read_coils,
        "discrete_input": client.read_discrete_inputs,
        "input_register": client.read_input_registers,
        "holding_register": client.read_holding_registers,
    }[m.object_type]
    return call(address, count=count, device_id=m.device_number)


def find(maps: list[PointMap], tag: str) -> PointMap:
    return next(m for m in maps if m.tag == tag)


@pytest.mark.req("ADC-PRO-001")
def test_every_mapped_point_reads_as_the_point_database_holds_it(site: Any) -> None:
    _, _, points, maps, _, client = site
    assert len(maps) > 300
    for m in maps:
        record = points.read(m.tag)
        bits = m.object_type in ("coil", "discrete_input")
        width = 1 if bits else ModbusView.width(record.kind, m.writable)
        answer = read(client, m, width)
        assert not answer.isError(), (m.tag, answer)
        raw = answer.bits[:1] if bits else answer.registers
        value = decode(raw, points.declaration(m.tag), m.writable)
        if isinstance(record.value, float):
            assert value == pytest.approx(record.value, rel=1e-6, abs=1e-6), m.tag
        else:
            assert value == record.value, m.tag


@pytest.mark.req("ADC-PRO-001")
def test_a_value_that_changes_in_the_plant_changes_on_the_wire(site: Any) -> None:
    kernel, plant, points, maps, _, client = site
    plant.module("cooling.tes", "TES-1").inject("set_charge", pct=42.0)
    kernel.run_for(1000)
    m = find(maps, "cooling.tes[TES-1].charge_pct")
    answer = read(client, m, 2)
    assert struct.unpack(">f", struct.pack(">HH", *answer.registers))[0] == pytest.approx(
        42.0, abs=0.5
    )
    assert points.read(m.tag).value == pytest.approx(42.0, abs=0.5)


@pytest.mark.req("ADC-PRO-001")
def test_illegal_address_value_and_function_get_the_right_exception(site: Any) -> None:
    _, _, points, maps, _, client = site
    setpoint = find(maps, DP_SP)
    unit = setpoint.device_number
    before = points.read(DP_SP).value
    address = int(setpoint.address) - 40001
    assert client.read_holding_registers(900, count=2, device_id=unit).exception_code == 2
    assert client.read_input_registers(5000, count=1, device_id=unit).exception_code == 2
    too_high = struct.unpack(">HH", struct.pack(">f", 9999.0))
    refused = client.write_registers(address, list(too_high), device_id=unit)
    assert refused.isError() and refused.exception_code == 3
    half = client.write_register(address, 1, device_id=unit)
    assert half.isError() and half.exception_code in (2, 3), "half a value is not a value"
    masked = client.mask_write_register(address=address, and_mask=0, or_mask=1, device_id=unit)
    assert masked.isError() and masked.exception_code == 1, "a function the device does not serve"
    assert points.read(DP_SP).value == before, "nothing was written"


@pytest.mark.req("ADC-PRO-001")
def test_a_writable_point_is_written_and_read_back(site: Any) -> None:
    kernel, plant, points, maps, _, client = site
    setpoint = find(maps, DP_SP)
    address = int(setpoint.address) - 40001
    words = struct.unpack(">HH", struct.pack(">f", 100.0))
    assert not client.write_registers(
        address, list(words), device_id=setpoint.device_number
    ).isError()
    assert points.read(DP_SP).value == 100.0
    start = find(maps, TEST_START)
    assert start.object_type == "coil"
    assert not client.write_coil(
        int(start.address) - 1, True, device_id=start.device_number
    ).isError()
    kernel.run_for(15_000)
    assert plant.module("electrical.genset", "A").io["state"] == "READY_TO_LOAD"
    client.write_coil(int(start.address) - 1, False, device_id=start.device_number)
    client.write_registers(address, list(struct.unpack(">HH", struct.pack(">f", 150.0))),
                           device_id=setpoint.device_number)  # fmt: skip
    kernel.run_for(2000)


@pytest.mark.req("ADC-PRO-001")
def test_a_write_to_a_read_only_register_is_refused_and_recorded(site: Any) -> None:
    kernel, _, points, maps, server, client = site
    timer = find(maps, TDEN)
    assert timer.object_type == "holding_register" and not timer.writable
    before = points.read(TDEN).value
    words = struct.unpack(">HH", struct.pack(">f", 1.0))
    seen: list[Any] = []
    kernel.events.subscribe("net.device_violation", seen.append)
    refused = client.write_registers(
        int(timer.address) - 40001, list(words), device_id=timer.device_number
    )
    assert refused.isError() and refused.exception_code == 2
    assert points.read(TDEN).value == before
    violations = server.view.violations()
    assert violations and violations[-1]["tag"] == TDEN
    assert violations[-1]["device"] == timer.device and violations[-1]["function"] == 16
    assert seen and seen[-1].payload["device"] == timer.device


def test_protection_and_life_safety_are_not_on_the_wire(site: Any) -> None:
    _, _, _, maps, server, _ = site
    served = {m.tag for m in maps}
    assert not [t for t in served if t.startswith(("life_safety[", "security["))]
    assert "electrical.power_train[A].gen_brk_close_cmd" not in served
    assert len(server.view.devices()) == len({m.device for m in maps})


@pytest.mark.req("ADC-SAF-001")
def test_the_server_refuses_to_bind_outside_the_simulators_own_networks(site: Any) -> None:
    _, _, _, _, server, _ = site
    other = ModbusServer(server.view)
    with pytest.raises(ExternalAddressError):
        other.start("0.0.0.0", 0)  # noqa: S104
    with pytest.raises(ExternalAddressError):
        other.start("192.0.2.10", 15020)
