"""The committed profiles: schema, provenance and wiring (ADC-PRV-003, -004)."""

import json
import subprocess
from pathlib import Path

import pytest

from agentic_datacenter.core.profile import Profile, build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel

REPO = Path(__file__).resolve().parents[2]
PROFILES = sorted((REPO / "profiles").glob("*.yaml"))
GENERIC = REPO / "profiles/generic_dc.yaml"


def test_the_public_default_profile_exists() -> None:
    assert GENERIC in PROFILES


@pytest.mark.req("ADC-PRV-004")
@pytest.mark.parametrize("path", PROFILES, ids=lambda p: p.name)
def test_committed_profile_satisfies_the_schema(path: Path) -> None:
    load_profile(path)


@pytest.mark.req("ADC-PRV-003")
def test_restricted_profile_is_ignored_and_not_tracked() -> None:
    ignored = (REPO / ".gitignore").read_text(encoding="utf-8").splitlines()
    assert "profiles/restricted_ref.yaml" in ignored
    tracked = subprocess.run(
        ["git", "ls-files", "profiles"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split()
    assert "profiles/restricted_ref.yaml" not in tracked


@pytest.mark.req("ADC-PRV-003")
def test_public_default_cites_no_restricted_source() -> None:
    text = GENERIC.read_text(encoding="utf-8").lower()
    assert "restricted_ref" not in text and "source: restricted" not in text
    assert "reference specification" not in text


def test_committed_json_schema_matches_the_code() -> None:
    committed = json.loads((REPO / "profiles/schema.json").read_text(encoding="utf-8"))
    assert committed == Profile.model_json_schema(), "run: uv run agentic-datacenter profile schema"


def test_generic_profile_wires_every_module_of_the_design() -> None:
    profile = load_profile(GENERIC)
    registry = ModuleRegistry.from_entry_points()
    plant = build_plant(profile, Kernel(seed=1), registry)
    used = {i.module_id for i in profile.instances()}
    assert used == {m.id for m in registry.manifests()}
    assert len(plant.wiring()) > 100


def test_generic_profile_has_the_facility_of_the_design() -> None:
    profile = load_profile(GENERIC)
    count: dict[str, int] = {}
    for inst in profile.instances():
        count[inst.module_id] = count.get(inst.module_id, 0) + 1
    assert count["electrical.power_train"] == 3
    assert count["electrical.genset"] == 3
    assert count["electrical.ups"] == 3
    assert count["electrical.it_load"] == 16
    assert count["cooling.pod"] == 16
    assert count["electrical.utility"] == 2
