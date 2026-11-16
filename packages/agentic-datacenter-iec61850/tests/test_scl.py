"""SCL generation (SDD 8.5, "Engineering files"): deterministic, complete, readable back."""

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

# The optional package is absent in most jobs (ADC-IEC-005).
pytest.importorskip("agentic_datacenter_iec61850")

from agentic_datacenter.core.profile import build_plant, load_profile  # noqa: E402
from agentic_datacenter.core.registry import ModuleRegistry  # noqa: E402
from agentic_datacenter.core.scheduler import Kernel  # noqa: E402
from agentic_datacenter.supervisory.points import PointDatabase  # noqa: E402
from agentic_datacenter_iec61850 import scl  # noqa: E402
from agentic_datacenter_iec61850.cli import main  # noqa: E402
from agentic_datacenter_iec61850.model import LOGICAL_NODES, Relay, relays  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
PROFILE = REPO / "profiles/generic_dc.yaml"
NS = "{http://www.iec.ch/61850/2003/SCL}"


def site(seed: int = 1) -> tuple[PointDatabase, list[Relay]]:
    kernel = Kernel(seed=seed)
    plant = build_plant(load_profile(PROFILE), kernel, ModuleRegistry.from_entry_points())
    points = PointDatabase(kernel, plant)
    return points, relays(points)


POINTS, RELAYS = site()


@pytest.mark.req("ADC-IEC-001")
def test_the_profile_gives_six_relays_with_the_logical_nodes_of_section_8_5() -> None:
    assert [(r.tag, r.kind) for r in RELAYS] == [
        ("IED-BUS", "bus"), ("IED-FDR-A", "feeder"), ("IED-FDR-B", "feeder"),
        ("IED-FDR-C", "feeder"), ("IED-INC-1", "incomer"), ("IED-INC-2", "incomer"),
    ]  # fmt: skip
    classes = {
        kind: [n.rstrip("0123456789") for n in nodes] for kind, nodes in LOGICAL_NODES.items()
    }
    assert classes["incomer"] == ["LLN", "LPHD", "XCBR", "CSWI", "MMXU", "PTOC", "PIOC", "PTUV",
                                  "PTOV", "PTRC"]  # fmt: skip
    assert classes["bus"] == ["LLN", "LPHD", "MMXU", "PTUV", "PTOV", "PTUF", "PTOF"]
    assert classes["feeder"] == ["LLN", "LPHD", "XCBR", "CSWI", "MMXU", "PTOC", "PIOC", "PTRC"]


def test_the_scd_is_the_same_bytes_whatever_the_seed_and_the_order() -> None:
    text = scl.scd(RELAYS)
    assert text == scl.scd(list(reversed(RELAYS))) == scl.scd(site(seed=7)[1])
    assert text.startswith('<?xml version="1.0" encoding="UTF-8"?>\n<SCL ')
    assert "2026" not in text.replace("Agentic-Datacenter", ""), "no date in a generated file"


def test_the_scd_is_well_formed_and_every_type_it_names_is_defined() -> None:
    root = ET.fromstring(scl.scd(RELAYS))
    assert root.tag == f"{NS}SCL"
    assert [ied.get("desc") for ied in root.findall(f"{NS}IED")] == [r.tag for r in RELAYS]
    connected = root.findall(f"{NS}Communication/{NS}SubNetwork/{NS}ConnectedAP")
    assert [c.get("iedName") for c in connected] == [r.name for r in RELAYS]
    templates = root.find(f"{NS}DataTypeTemplates")
    assert templates is not None
    defined = {t.get("id") for t in templates}
    used = {e.get("lnType") for e in root.iter() if e.get("lnType")}
    used |= {e.get("type") for e in templates.iter() if e.get("type")}
    assert used <= defined and defined <= used, "nothing missing, nothing unused"


@pytest.mark.req("ADC-IEC-001")
def test_reading_the_scd_back_gives_every_relay_and_every_bound_attribute() -> None:
    ieds = {ied.tag: ied for ied in scl.parse(scl.scd(RELAYS))}
    assert list(ieds) == [r.tag for r in RELAYS]
    for relay in RELAYS:
        ied = ieds[relay.tag]
        assert ied.name == relay.name and ied.kind == relay.kind
        assert ied.logical_nodes == LOGICAL_NODES[relay.kind]
        leaves = {(leaf.ref, leaf.fc) for leaf in ied.leaves}
        assert len(leaves) == len(ied.leaves)
        for binding in relay.bindings:
            assert (binding.ref, binding.fc) in leaves, binding
            assert POINTS.read(binding.tag).tag == binding.tag
        assert [d.name for d in ied.data_sets] == ["dsEvents", "dsMeas"]
        assert [(r.name, r.buffered) for r in ied.reports] == [
            ("brcbEvents01", True), ("urcbEvents01", False), ("urcbMeas01", False),
        ]  # fmt: skip
        assert ied.setting_groups == (1, 1)
        models = [leaf for leaf in ied.leaves if leaf.ref.endswith(".ctlModel")]
        assert models and all((m.value, m.ordinal) == ("status-only", 0) for m in models)


@pytest.mark.req("ADC-IEC-001")
def test_every_mapped_status_and_measurement_of_the_switchboard_is_served_by_a_relay() -> None:
    bound = {b.tag for r in RELAYS for b in r.bindings}
    switchboard = [t for t in POINTS.tags() if t.startswith("electrical.mv_switchgear[")]
    unserved = sorted(set(switchboard) - bound)
    # The operating time of the last trip has no data object in the logical nodes of 8.5.
    assert all(tag.endswith("_operate_s") for tag in unserved), unserved


def test_one_icd_per_relay_type(tmp_path: Path) -> None:
    for kind in ("bus", "feeder", "incomer"):
        (ied,) = scl.parse(scl.icd(kind, RELAYS))
        assert ied.name == "TEMPLATE" and ied.logical_nodes == LOGICAL_NODES[kind]
    with pytest.raises(scl.SclError):
        scl.icd("transformer", RELAYS)
    with pytest.raises(scl.SclError):
        scl.parse("<SCL/>")
    written = scl.export(RELAYS, tmp_path)
    assert [p.name for p in written] == ["bus.icd", "feeder.icd", "incomer.icd", "site.scd"]
    assert (tmp_path / "site.scd").read_text(encoding="utf-8") == scl.scd(RELAYS)


def test_the_scl_export_command_writes_the_files(tmp_path: Path) -> None:
    out = tmp_path / "scl"
    assert main(["export", "--profile", str(PROFILE), "--out", str(out)]) == 0
    assert sorted(p.name for p in out.iterdir()) == [
        "bus.icd",
        "feeder.icd",
        "incomer.icd",
        "site.scd",
    ]
    assert (out / "site.scd").read_text(encoding="utf-8") == scl.scd(RELAYS)
