"""The equipment registry's gate: no entry without its source, its licence and its rights (ADR 0034)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from agentic_datacenter.core.equipment import Entry, RegistryError, load_entry, load_registry
from agentic_datacenter.core.facility import load_facility
from agentic_datacenter.core.profile import build_plant
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO / "equipment"
SOURCES: dict[str, Any] = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
ENTRIES = load_registry(ROOT)
NOTICES = (REPO / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")


@pytest.mark.req("ADC-EQP-001")
def test_the_registry_has_entries_and_each_is_valid_and_where_it_belongs() -> None:
    assert len(ENTRIES) >= 8
    for path in sorted(ROOT.glob("*/*.yaml")):
        entry = load_entry(path.stem, ROOT)
        assert path.parent.name == entry.module


@pytest.mark.req("ADC-EQP-001")
def test_every_entry_names_a_pinned_source_and_every_value_cites_it() -> None:
    for entry in ENTRIES.values():
        source = SOURCES[entry.provenance.source]
        assert len(source["commit"]) == 40
        assert (REPO / source["licence_file"]).is_file()
        for name, param in entry.params.items():
            assert param.source is not None
            assert param.source.startswith(entry.provenance.source), (entry.id, name)
            assert source["commit"][:12] in param.source, (entry.id, name)
            assert any(path in param.source for path in source["files"]), (entry.id, name)


@pytest.mark.req("ADC-EQP-002")
def test_every_entry_may_be_used_commercially_and_redistributed() -> None:
    for entry in ENTRIES.values():
        assert entry.rights.commercial_use == "allowed", entry.id
        assert entry.rights.redistribution == "allowed", entry.id
        assert entry.provenance.redistributes_source_document is False


def _entry(**change: Any) -> dict[str, Any]:
    data = yaml.safe_load(next(ROOT.glob("*/*.yaml")).read_text(encoding="utf-8"))
    for dotted, value in change.items():
        *path, last = dotted.split("__")
        node = data
        for key in path:
            node = node[key]
        node[last] = value
    return data


@pytest.mark.req("ADC-EQP-002")
@pytest.mark.parametrize(
    "change",
    [
        {"tier": "vendor_verified"},  # a tier not earned: no verification named
        {"simulation__manufacturer_validated": True},
        {"tier": "calibrated"},  # calibrated, but simulation.calibration says otherwise
        {"provenance__redistributes_source_document": True},
        {"rights__commercial_use": "maybe"},
        {"params__cop": {"value": 4.0, "unit": "-", "assumed": True}},
    ],
)
def test_an_entry_that_claims_more_than_it_shows_is_refused(change: dict[str, Any]) -> None:
    with pytest.raises(ValueError):
        Entry.model_validate(_entry(**change))


@pytest.mark.req("ADC-EQP-002")
def test_the_gate_refuses_rights_pending_review() -> None:
    entry = Entry.model_validate(_entry(rights__redistribution="pending_review"))
    assert entry.rights.redistribution != "allowed"  # valid as data, refused by the gate above


@pytest.mark.req("ADC-EQP-003")
def test_every_value_of_every_entry_is_read_by_its_module(tmp_path: Path) -> None:
    for entry_id, entry in ENTRIES.items():
        bundle = tmp_path / entry_id
        bundle.mkdir()
        generic = yaml.safe_load((REPO / "profiles/generic_dc.yaml").read_text(encoding="utf-8"))
        generic.pop("schema_version")
        for use in generic["modules"]:
            if use["id"] == entry.module:
                use["equipment"] = f"registry:{entry_id}"
        (bundle / "datacenter.yaml").write_text(
            yaml.safe_dump({"schema_version": 2, **generic}), encoding="utf-8"
        )
        facility = load_facility(bundle, registry=ROOT)
        build_plant(facility.profile, Kernel(seed=1), ModuleRegistry.from_entry_points())
        assert facility.equipment[f"registry:{entry_id}"].maker == entry.maker


@pytest.mark.req("ADC-EQP-003")
def test_a_bundle_that_names_an_entry_the_registry_lacks_is_refused(tmp_path: Path) -> None:
    (tmp_path / "datacenter.yaml").write_text(
        yaml.safe_dump(
            {
                "schema_version": 2, "name": "x", "site": "S",
                "modules": [{"id": "cooling.chw_plant", "instances": ["CHW"],
                             "equipment": "registry:modelica.nobody_nothing"}],
            }
        ),
        encoding="utf-8",
    )  # fmt: skip
    with pytest.raises(RegistryError, match="nobody_nothing"):
        load_facility(tmp_path, registry=ROOT)


@pytest.mark.req("ADC-EQP-004")
def test_the_notices_name_every_source_with_its_commit_and_licence_file() -> None:
    for source in SOURCES.values():
        assert source["repository"] in NOTICES
        assert source["commit"] in NOTICES
        assert source["licence_file"] in NOTICES
