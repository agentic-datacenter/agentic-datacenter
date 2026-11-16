"""ADC-MOD-001, -004, -005, ADC-FID-001, ADC-DOC-002 over the real plant modules."""

from pathlib import Path

import pytest
import yaml

from agentic_datacenter.core.contract import check_module
from agentic_datacenter.core.module import load_manifest
from agentic_datacenter.core.registry import ModuleRegistry

REPO = Path(__file__).resolve().parents[2]
PLANT = REPO / "packages/agentic-datacenter-plant/src/agentic_datacenter/plant"

# The sixteen modules of SDD 5.1 and the repository layout in 5.4.
EXPECTED = {
    "electrical.utility", "electrical.mv_switchgear", "electrical.power_train",
    "electrical.genset", "electrical.ups", "electrical.it_load",
    "cooling.chw_plant", "cooling.pump_station", "cooling.tes",
    "cooling.pod", "cooling.eroom", "cooling.weather",
    "fuel", "life_safety", "security", "sensors",
}  # fmt: skip

SPEC_SECTIONS = [
    "Purpose", "Ports", "Equations", "State machine", "Points",
    "Parameters", "Faults", "Validation cases", "Known limits",
]  # fmt: skip

REGISTRY = ModuleRegistry.from_entry_points()
ENTRIES = {entry.manifest.id: entry for entry in REGISTRY.entries()}


def module_dir(module_id: str) -> Path:
    return PLANT.joinpath(*module_id.split("."))


@pytest.mark.req("ADC-MOD-001")
def test_the_sixteen_modules_of_the_design_are_registered() -> None:
    assert set(ENTRIES) == EXPECTED


@pytest.mark.req("ADC-MOD-001")
@pytest.mark.parametrize("module_id", sorted(EXPECTED))
def test_module_directory_holds_a_valid_manifest_with_its_own_id(module_id: str) -> None:
    manifest = load_manifest(module_dir(module_id) / "module.yaml")
    assert manifest.id == module_id
    assert manifest == ENTRIES[module_id].manifest


@pytest.mark.req("ADC-MOD-001")
@pytest.mark.parametrize("module_id", sorted(EXPECTED))
def test_module_directory_has_the_files_of_a_vertical_slice(module_id: str) -> None:
    present = {p.name for p in module_dir(module_id).iterdir()}
    assert {"module.yaml", "stub.py", "README.md", "__init__.py"} <= present


@pytest.mark.req("ADC-MOD-004")
@pytest.mark.parametrize("module_id", sorted(EXPECTED))
def test_module_and_its_stub_pass_the_contract_suite(module_id: str) -> None:
    check_module(ENTRIES[module_id])


@pytest.mark.req("ADC-FID-001")
@pytest.mark.parametrize("module_id", sorted(EXPECTED))
def test_module_declares_a_fidelity_level(module_id: str) -> None:
    assert ENTRIES[module_id].manifest.fidelity in {"F0", "F1", "F2", "F3"}


@pytest.mark.req("ADC-DOC-002")
@pytest.mark.parametrize("module_id", sorted(EXPECTED))
def test_module_spec_exists_with_every_template_section(module_id: str) -> None:
    spec = REPO / ENTRIES[module_id].manifest.spec
    assert spec.name == f"{module_id}.md"
    headings = [
        line[3:].strip()
        for line in spec.read_text(encoding="utf-8").splitlines()
        if line.startswith("## ")
    ]
    assert headings == SPEC_SECTIONS


@pytest.mark.req("ADC-DOC-002")
def test_every_adr_has_a_status() -> None:
    adrs = sorted((REPO / "docs/design/adr").glob("[0-9]*.md"))
    assert adrs
    without = [p.name for p in adrs if "**Status:**" not in p.read_text(encoding="utf-8")]
    assert without == []


@pytest.mark.req("ADC-MOD-005")
def test_modules_lock_matches_the_manifests() -> None:
    committed = yaml.safe_load((REPO / "modules.lock.yaml").read_text(encoding="utf-8"))
    assert committed == REGISTRY.lock_data(), "run: uv run agentic-datacenter modules lock"


@pytest.mark.req("ADC-MOD-005")
def test_every_requirement_a_module_claims_exists_in_the_design_document() -> None:
    import re

    sdd = (REPO / "docs/design/SDD-ADC-001.md").read_text(encoding="utf-8")
    known = set(re.findall(r"ADC-[A-Z]{2,3}-\d{3}", sdd.replace("\\_", "_")))
    claimed = {r for e in ENTRIES.values() for r in e.manifest.requirements}
    assert claimed and claimed <= known
