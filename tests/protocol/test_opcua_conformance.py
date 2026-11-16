"""ADC-PRO-001 for OPC UA: the server is a read-only view of the point database (ADR 0015)."""

import asyncio
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from asyncua import Client as AsyncClient
from asyncua import ua
from asyncua.crypto import cert_gen
from asyncua.sync import Client
from cryptography.x509.oid import ExtendedKeyUsageOID

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.net.guard import ExternalAddressError
from agentic_datacenter.net.maps import PointMap, protocol_maps
from agentic_datacenter.net.opcua import (
    NAMESPACE_URI,
    SIM_EPOCH,
    STATUS_OF_QUALITY,
    InsecureEndpointError,
    OpcUaServer,
    OpcUaView,
)
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[2]
DP_SP = "cooling.pump_station[PHPS].dp_sp_kpa"
CHARGE = "cooling.tes[TES-1].charge_pct"
TYPE_OF_KIND = {
    "analog_in": ua.VariantType.Double,
    "analog_setting": ua.VariantType.Double,
    "binary_in": ua.VariantType.Boolean,
    "binary_cmd": ua.VariantType.Boolean,
    "counter": ua.VariantType.UInt64,
    "enum_status": ua.VariantType.String,
}


@pytest.fixture(scope="module")
def site() -> Iterator[tuple[Kernel, Any, PointDatabase, list[PointMap], OpcUaServer, Client]]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    kernel.run_for(5000)
    maps = [m for m in protocol_maps(points) if m.protocol == "opcua"]
    server = OpcUaServer(OpcUaView(kernel, points, maps))
    port = server.start("127.0.0.1", 0)
    client = Client(f"opc.tcp://127.0.0.1:{port}", timeout=10)
    client.connect()
    yield kernel, plant, points, maps, server, client
    client.disconnect()
    server.stop()


def read_all(client: Client, node_ids: list[str]) -> list[ua.DataValue]:
    answers: list[ua.DataValue] = client.read_attributes([client.get_node(n) for n in node_ids])
    return answers


def read_one(client: Client, node_id: str) -> ua.DataValue:
    return read_all(client, [node_id])[0]


def status(answer: ua.DataValue) -> int:
    assert answer.StatusCode is not None
    return int(answer.StatusCode.value)


@pytest.mark.req("ADC-PRO-001")
def test_the_view_maps_every_node_id_to_its_tag_and_back(site: Any) -> None:
    _, _, points, maps, server, _ = site
    view = server.view
    assert view.node_ids() == sorted(str(m.address) for m in maps)
    for m in maps:
        assert m.address == f"ns=2;s={m.tag}"
        assert view.tag_of(str(m.address)) == m.tag and view.node_of(m.tag) == m.address
        assert view.variant_type(m.tag) == TYPE_OF_KIND[points.read(m.tag).kind], m.tag
    with pytest.raises(KeyError):
        view.tag_of("ns=2;s=no.such[X].point")
    assert view.devices() == sorted({m.tag.rpartition(".")[0] for m in maps})


@pytest.mark.req("ADC-PRO-001")
def test_browsing_from_the_objects_folder_finds_every_mapped_point(site: Any) -> None:
    _, _, _, maps, server, client = site
    assert client.get_namespace_array()[2] == NAMESPACE_URI
    devices = [
        node for node in client.nodes.objects.get_children() if node.nodeid.NamespaceIndex == 2
    ]
    assert [node.nodeid.to_string() for node in devices] == [
        f"ns=2;s={device}" for device in server.view.devices()
    ]
    found = []
    for device in devices:
        for child in device.get_children():
            node_id = child.nodeid.to_string()
            assert node_id.startswith(device.nodeid.to_string() + ".")
            found.append(node_id)
    assert len(found) > 700
    assert sorted(found) == sorted(str(m.address) for m in maps)
    one = client.get_node(f"ns=2;s={DP_SP}")
    assert one.read_browse_name().Name == "dp_sp_kpa"
    assert one.read_node_class() == ua.NodeClass.Variable


@pytest.mark.req("ADC-PRO-001")
def test_every_node_reads_as_the_point_database_holds_it(site: Any) -> None:
    kernel, _, points, maps, _, client = site
    now = SIM_EPOCH + timedelta(milliseconds=kernel.clock.now_ms)
    answers = read_all(client, [str(m.address) for m in maps])
    assert len(answers) == len(maps) > 700
    for m, answer in zip(maps, answers, strict=True):
        record = points.read(m.tag)
        assert answer.Value is not None, m.tag
        assert answer.Value.VariantType == TYPE_OF_KIND[record.kind], m.tag
        assert answer.Value.Value == record.value, m.tag
        assert type(answer.Value.Value) is type(record.value) or record.kind.startswith("analog")
        assert record.quality == "good" and status(answer) == ua.StatusCodes.Good, m.tag
        assert answer.SourceTimestamp == SIM_EPOCH + timedelta(milliseconds=record.time_ms), m.tag
        assert answer.ServerTimestamp == now, m.tag


@pytest.mark.req("ADC-PRO-001")
def test_a_value_that_changes_in_the_plant_changes_on_the_wire(site: Any) -> None:
    kernel, plant, points, _, _, client = site
    plant.module("cooling.tes", "TES-1").inject("set_charge", pct=42.0)
    kernel.run_for(1000)
    answer = read_one(client, f"ns=2;s={CHARGE}")
    assert answer.Value is not None and answer.Value.Value == pytest.approx(42.0, abs=0.5)
    assert answer.Value.Value == points.read(CHARGE).value
    assert answer.ServerTimestamp == SIM_EPOCH + timedelta(milliseconds=kernel.clock.now_ms)


@pytest.mark.req("ADC-PRO-001")
def test_the_status_code_follows_the_point_quality(site: Any) -> None:
    kernel, _, points, _, server, client = site
    assert STATUS_OF_QUALITY == {
        "good": ua.StatusCodes.Good,
        "uncertain": ua.StatusCodes.Uncertain,
        "stale": ua.StatusCodes.UncertainLastUsableValue,
        "bad": ua.StatusCodes.Bad,
    }
    held = points.read(CHARGE)
    points.set_link(False)
    try:
        kernel.run_for(4000)
        record = points.read(CHARGE)
        assert record.quality == "stale" and record.value == held.value
        answer = read_one(client, f"ns=2;s={CHARGE}")
        assert status(answer) == ua.StatusCodes.UncertainLastUsableValue
        assert answer.Value is not None and answer.Value.Value == held.value
        assert answer.SourceTimestamp == SIM_EPOCH + timedelta(milliseconds=record.time_ms)
        assert answer.ServerTimestamp == SIM_EPOCH + timedelta(milliseconds=kernel.clock.now_ms)
        assert answer.SourceTimestamp < answer.ServerTimestamp
        assert server.view.data_value(CHARGE) == answer, "the socket adds nothing to the view"
    finally:
        points.set_link(True)
    kernel.run_for(1000)
    assert status(read_one(client, f"ns=2;s={CHARGE}")) == ua.StatusCodes.Good


@pytest.mark.req("ADC-PRO-001")
def test_an_unknown_node_and_a_missing_attribute_get_the_right_status(site: Any) -> None:
    _, _, _, _, _, client = site
    assert status(read_one(client, "ns=2;s=no.such[X].point")) == ua.StatusCodes.BadNodeIdUnknown
    assert status(read_one(client, f"ns=3;s={DP_SP}")) == ua.StatusCodes.BadNodeIdUnknown
    with pytest.raises(ua.uaerrors.BadNodeIdUnknown):
        client.get_node("ns=2;s=no.such[X].point").read_value()
    with pytest.raises(ua.uaerrors.BadAttributeIdInvalid):
        client.get_node(f"ns=2;s={DP_SP}").read_attribute(ua.AttributeIds.Executable)


@pytest.mark.req("ADC-PRO-001")
def test_every_write_is_refused_and_recorded(site: Any) -> None:
    kernel, _, points, _, server, client = site
    node = client.get_node(f"ns=2;s={DP_SP}")
    access = node.read_attribute(ua.AttributeIds.AccessLevel).Value.Value
    user_access = node.read_attribute(ua.AttributeIds.UserAccessLevel).Value.Value
    assert access == user_access == 1 << ua.AccessLevel.CurrentRead, "read access and nothing else"
    before = points.read(DP_SP).value
    seen: list[Any] = []
    kernel.events.subscribe("net.device_violation", seen.append)
    for value in (100.0, 9999.0):  # one the point would take, one out of its range
        with pytest.raises(ua.uaerrors.BadUserAccessDenied):
            node.write_value(value)
    with pytest.raises(ua.uaerrors.BadUserAccessDenied):
        node.write_attribute(
            ua.AttributeIds.AccessLevel, ua.DataValue(ua.Variant(3, ua.VariantType.Byte))
        )
    assert node.read_attribute(ua.AttributeIds.AccessLevel).Value.Value == access
    assert points.read(DP_SP).value == before, "nothing was written"
    assert read_one(client, f"ns=2;s={DP_SP}").Value.Value == before  # type: ignore[union-attr]
    violations = server.view.violations()
    assert len(violations) == 3 and len(seen) == 3
    assert violations[0]["tag"] == DP_SP and violations[0]["device"] == "opcua-server"
    assert violations[0]["node"] == f"ns=2;s={DP_SP}"
    assert violations[0]["time_ms"] == kernel.clock.now_ms
    assert seen[-1].payload["tag"] == DP_SP


def test_protection_and_life_safety_are_not_on_the_wire(site: Any) -> None:
    _, _, points, maps, _, client = site
    served = {m.tag for m in maps}
    assert not [t for t in served if t.startswith(("life_safety[", "security["))]
    assert "electrical.power_train[A].gen_brk_close_cmd" not in served
    hidden = next(t for t in points.tags() if t.startswith("life_safety["))
    assert status(read_one(client, f"ns=2;s={hidden}")) == ua.StatusCodes.BadNodeIdUnknown


@pytest.mark.req("ADC-SAF-001")
def test_the_server_refuses_to_bind_outside_the_simulators_own_networks(site: Any) -> None:
    _, _, _, _, server, _ = site
    other = OpcUaServer(server.view)
    with pytest.raises(ExternalAddressError):
        other.start("0.0.0.0", 0)  # noqa: S104
    with pytest.raises(ExternalAddressError):
        other.start("192.0.2.10", 14840)
    with pytest.raises(InsecureEndpointError):
        # Without a certificate the override does not help: unsecured is loopback only.
        other.start("192.0.2.10", 14840, allow_external=True)


@pytest.mark.req("ADC-PRO-001")
def test_with_a_certificate_only_a_signed_and_encrypted_session_reads(
    site: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _, _, points, _, server, _ = site
    for who in ("server", "client"):
        asyncio.run(
            cert_gen.setup_self_signed_certificate(
                tmp_path / f"{who}.pem",
                tmp_path / f"{who}.der",
                f"urn:agentic-datacenter:opcua-{who}",
                "localhost",
                [ExtendedKeyUsageOID.CLIENT_AUTH, ExtendedKeyUsageOID.SERVER_AUTH],
                {"commonName": f"agentic-datacenter test {who}"},
            )
        )
    secured = OpcUaServer(
        server.view, certificate=tmp_path / "server.der", private_key=tmp_path / "server.pem"
    )
    port = secured.start("127.0.0.1", 0)
    url = f"opc.tcp://127.0.0.1:{port}"
    try:
        client = Client(url, timeout=10)
        client.application_uri = "urn:agentic-datacenter:opcua-client"
        client.set_security_string(
            f"Basic256Sha256,SignAndEncrypt,{tmp_path / 'client.der'},{tmp_path / 'client.pem'}"
        )
        client.connect()
        try:
            offered = {
                (e.SecurityPolicyUri.rpartition("#")[2], e.SecurityMode)
                for e in client.get_endpoints()
            }
            assert offered == {("Basic256Sha256", ua.MessageSecurityMode.SignAndEncrypt)}
            answer = read_one(client, f"ns=2;s={DP_SP}")
            assert answer.Value is not None and answer.Value.Value == points.read(DP_SP).value
        finally:
            client.disconnect()
        # A client that ignores the endpoint list and stays on an unsecured channel.
        monkeypatch.setattr(
            AsyncClient, "find_endpoint", staticmethod(lambda endpoints, *_: next(iter(endpoints)))
        )
        plain = Client(url, timeout=10)
        try:
            with pytest.raises(ua.uaerrors.BadUserAccessDenied):
                plain.connect()
        finally:
            plain.disconnect()
    finally:
        secured.stop()
