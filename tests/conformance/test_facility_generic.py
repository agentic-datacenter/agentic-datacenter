"""The generic facility under ADR 0033: its hash, its build and its parameters."""

import json
from pathlib import Path

import pytest
import yaml

from agentic_datacenter.core.facility import load_facility
from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry, WiringError
from agentic_datacenter.core.scheduler import Kernel

REPO = Path(__file__).resolve().parents[2]
GENERIC = REPO / "profiles/generic_dc.yaml"


@pytest.mark.req("ADC-FAC-002")
def test_the_generic_profile_keeps_the_hash_of_the_frozen_version() -> None:
    frozen = json.loads((REPO / "docs/bench/VERSION.json").read_text(encoding="utf-8"))
    assert load_profile(GENERIC).hash() == frozen["version"]["profile"]
    assert load_facility(GENERIC).profile.hash() == frozen["version"]["profile"]


@pytest.mark.req("ADC-FAC-004")
def test_every_parameter_of_the_generic_profile_is_read_by_its_module() -> None:
    build_plant(load_profile(GENERIC), Kernel(seed=1), ModuleRegistry.from_entry_points())


@pytest.mark.req("ADC-FAC-004")
def test_a_misspelt_parameter_of_a_built_in_module_is_refused(tmp_path: Path) -> None:
    data = yaml.safe_load(GENERIC.read_text(encoding="utf-8"))
    pod = next(use for use in data["modules"] if use["id"] == "cooling.pod")
    pod["params"]["desing_it_kw"] = pod["params"].pop("design_it_kw")
    path = tmp_path / "typo.yaml"
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(WiringError, match="desing_it_kw"):
        build_plant(load_profile(path), Kernel(seed=1), ModuleRegistry.from_entry_points())
