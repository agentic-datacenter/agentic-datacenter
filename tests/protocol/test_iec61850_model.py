"""ADC-IEC-001: each relay serves the logical nodes of SDD 8.5, and exactly the generated SCD.

The served directory is walked with an MMS client on a real socket. The SCD
is expanded here, independently of the reader the server is built from.
"""

from typing import Any
from xml.etree import ElementTree as ET

import pytest

NS = "{http://www.iec.ch/61850/2003/SCL}"
#: SDD 8.5, by relay tag.
INCOMER = {"LLN0", "LPHD", "XCBR", "CSWI", "MMXU", "PTOC", "PIOC", "PTUV", "PTOV", "PTRC"}
FEEDER = {"LLN0", "LPHD", "XCBR", "CSWI", "MMXU", "PTOC", "PIOC", "PTRC"}
EXPECTED = {
    "IED-INC-1": INCOMER,
    "IED-INC-2": INCOMER,
    "IED-BUS": {"LLN0", "LPHD", "MMXU", "PTUV", "PTOV", "PTUF", "PTOF"},
    "IED-FDR-A": FEEDER,
    "IED-FDR-B": FEEDER,
    "IED-FDR-C": FEEDER,
}


def expand(scd: str) -> dict[str, dict[str, Any]]:
    """Return, per relay tag, what the SCD says it holds."""
    root = ET.fromstring(scd)
    types = {t.get("id"): t for t in root.find(f"{NS}DataTypeTemplates")}  # type: ignore[union-attr]

    def attributes(element: ET.Element, ref: str, fc: str) -> list[tuple[str, str]]:
        if element.tag in (f"{NS}DO", f"{NS}SDO"):
            return [
                pair
                for member in types[element.get("type")]
                for pair in attributes(member, f"{ref}.{member.get('name')}", member.get("fc", fc))
            ]
        if element.get("bType") == "Struct":
            return [
                pair
                for member in types[element.get("type")]
                for pair in attributes(member, f"{ref}.{member.get('name')}", fc)
            ]
        return [(ref, fc)]

    out = {}
    for ied in root.findall(f"{NS}IED"):
        device = ied.find(f"{NS}AccessPoint/{NS}Server/{NS}LDevice")
        assert device is not None
        nodes, leaves, sets, blocks = [], [], {}, {("SP", "SGCB")}
        for node in device:
            name = f"{node.get('lnClass')}{node.get('inst')}"
            nodes.append(name)
            for data in types[node.get("lnType")]:
                leaves += attributes(data, f"{device.get('inst')}/{name}.{data.get('name')}", "")
            for data_set in node.findall(f"{NS}DataSet"):
                sets[data_set.get("name")] = tuple(
                    f"{m.get('ldInst')}/{m.get('lnClass')}{m.get('lnInst')}.{m.get('doName')}"
                    f"[{m.get('fc')}]"
                    for m in data_set
                )
            for control in node.findall(f"{NS}ReportControl"):
                fc = "BR" if control.get("buffered") == "true" else "RP"
                blocks.add((fc, f"{control.get('name')}01"))
        out[str(ied.get("desc"))] = {
            "name": ied.get("name"), "nodes": nodes, "leaves": set(leaves), "sets": sets,
            "blocks": blocks,
        }  # fmt: skip
    return out


def connect(site: Any, relay: str) -> Any:
    from agentic_datacenter_iec61850.client import MmsClient

    return MmsClient("127.0.0.1", site.ports[relay])


@pytest.mark.req("ADC-IEC-001")
def test_six_relays_are_served_each_with_the_logical_nodes_of_section_8_5(relay_site: Any) -> None:
    assert set(relay_site.ports) == set(EXPECTED)
    assert len(set(relay_site.ports.values())) == 6, "one server, one port, per relay"
    for relay, classes in EXPECTED.items():
        with connect(relay_site, relay) as client:
            devices = client.logical_devices()
            served = client.directory().logical_nodes
        assert devices == [relay.replace("-", "_") + "LD0"]
        assert {name.rstrip("0123456789") if name != "LLN0" else name for name in served} == classes
        assert len(served) == len(classes), "one instance of each"


@pytest.mark.req("ADC-IEC-001")
def test_the_served_directory_equals_the_generated_scd(relay_site: Any) -> None:
    described = expand(relay_site.view.scd)
    assert set(described) == set(EXPECTED)
    for relay, scd in described.items():
        with connect(relay_site, relay) as client:
            directory = client.directory()
        assert directory.domain == f"{scd['name']}LD0"
        assert sorted(directory.logical_nodes) == sorted(scd["nodes"]), relay
        assert directory.attributes == scd["leaves"], relay
        assert len(directory.attributes) > 80
        assert directory.data_sets == scd["sets"], relay
        assert directory.control_blocks == scd["blocks"], relay


@pytest.mark.req("ADC-IEC-001")
def test_served_types_and_configured_values_are_those_of_the_scd(relay_site: Any) -> None:
    with connect(relay_site, "IED-FDR-A") as client:
        domain = client.directory().domain
        kinds = {
            ("XCBR1.Pos.stVal", "ST"): "bit-string",
            ("XCBR1.Pos.q", "ST"): "bit-string",
            ("XCBR1.Pos.t", "ST"): "utc-time",
            ("MMXU1.TotW.mag.f", "MX"): "float",
            ("PTRC1.Tr.general", "ST"): "boolean",
            ("PTOC1.StrVal.setMag.f", "SP"): "float",
            ("LLN0.NamPlt.d", "DC"): "visible-string",
        }
        for (ref, fc), kind in kinds.items():
            assert client.kind(f"{domain}/{ref}", fc) == kind, ref
        description = client.read(f"{domain}/LLN0.NamPlt.d", "DC")
        assert description.startswith("IED-FDR-A") and description in relay_site.view.scd
        # kW: unit W with multiplier k, as the SCD configures it.
        assert client.read(f"{domain}/MMXU1.TotW.units", "CF") == [62, 3]
        assert client.read(f"{domain}/LLN0.Beh.stVal", "ST") == 1
    with connect(relay_site, "IED-INC-1") as client:
        # The plant has no voltage elements on the incomers: served, and switched off.
        assert client.read("IED_INC_1LD0/PTUV1.Beh.stVal", "ST") == 5


@pytest.mark.req("ADC-IEC-001")
def test_every_control_object_is_served_status_only(relay_site: Any) -> None:
    controls = 0
    for relay, scd in expand(relay_site.view.scd).items():
        with connect(relay_site, relay) as client:
            for ref, fc in sorted(scd["leaves"]):
                if ref.endswith(".ctlModel"):
                    controls += 1
                    assert fc == "CF"
                    assert client.read(f"{scd['name']}{ref}", "CF") == 0, (relay, ref)
    assert controls >= 6 + 5 * 4, "Mod on every relay; Pos, Pos, BlkOpn, BlkCls with a breaker"
