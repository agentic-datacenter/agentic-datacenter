"""ADC-MOD-001: a module manifest is validated before anything loads."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentic_datacenter.core.module import ManifestError, load_manifest, parse_manifest

VALID: dict[str, Any] = {
    "id": "electrical.power_train",
    "version": "0.1.0",
    "fidelity": "F1",
    "provides": [
        {"port": "lv_bus", "type": "electrical"},
        {"port": "gen_start_request", "type": "signal"},
    ],
    "requires": [
        {"port": "utility_feed", "type": "electrical"},
        {"port": "gen_ready_to_load", "type": "signal"},
    ],
    "zone": "Z1-PWR-{instance}",
    "requirements": ["ADC-CTL-001", "ADC-CTL-002"],
    "spec": "docs/design/modules/electrical.power_train.md",
}


def changed(**updates: Any) -> dict[str, Any]:
    data = copy.deepcopy(VALID)
    for key, value in updates.items():
        if value is ...:
            data.pop(key)
        else:
            data[key] = value
    return data


@pytest.mark.req("ADC-MOD-001")
def test_valid_manifest_is_accepted() -> None:
    manifest = parse_manifest(VALID)
    assert manifest.id == "electrical.power_train"
    assert manifest.fidelity == "F1"
    assert [p.port for p in manifest.provides] == ["lv_bus", "gen_start_request"]
    assert manifest.zone_for("A") == "Z1-PWR-A"


@pytest.mark.req("ADC-MOD-001")
def test_single_level_id_is_accepted() -> None:
    assert parse_manifest(changed(id="fuel")).id == "fuel"


@pytest.mark.req("ADC-MOD-001")
@pytest.mark.parametrize(
    ("updates", "names"),
    [
        ({"id": ...}, "id"),
        ({"id": "Electrical.PowerTrain"}, "id"),
        ({"id": "a.b.c"}, "id"),
        ({"version": "1.0"}, "version"),
        ({"version": "v1.0.0"}, "version"),
        ({"fidelity": "F4"}, "fidelity"),
        ({"fidelity": ...}, "fidelity"),
        ({"provides": [{"port": "lv_bus", "type": "steam"}]}, "steam"),
        ({"provides": [{"port": "LV-Bus", "type": "electrical"}]}, "port"),
        ({"requires": [{"port": "feed", "type": "electrical", "keyed_by": "trains"}]}, "keyed_by"),
        ({"requirements": ["CTL-001"]}, "requirements"),
        ({"requirements": ...}, "requirements"),
        ({"spec": ...}, "spec"),
        ({"spec": "docs/modules/x.txt"}, "spec"),
        ({"zone": ...}, "zone"),
        ({"colour": "blue"}, "colour"),
    ],
)
def test_invalid_manifest_is_refused_and_names_the_problem(
    updates: dict[str, Any], names: str
) -> None:
    with pytest.raises(ManifestError, match=names):
        parse_manifest(changed(**updates))


@pytest.mark.req("ADC-MOD-001")
def test_port_name_used_twice_is_refused() -> None:
    data = changed(requires=[{"port": "lv_bus", "type": "electrical"}])
    with pytest.raises(ManifestError, match="lv_bus"):
        parse_manifest(data)


def test_keyed_provided_port_is_accepted() -> None:
    data = changed(provides=[{"port": "feeder", "type": "electrical", "keyed_by": "trains"}])
    assert parse_manifest(data).provides[0].keyed_by == "trains"


def test_manifest_is_read_from_a_yaml_file(tmp_path: Path) -> None:
    path = tmp_path / "module.yaml"
    path.write_text(yaml.safe_dump(VALID), encoding="utf-8")
    assert load_manifest(path).id == "electrical.power_train"


def test_file_that_is_not_a_mapping_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "module.yaml"
    path.write_text("- just\n- a list\n", encoding="utf-8")
    with pytest.raises(ManifestError, match="mapping"):
        load_manifest(path)


def test_missing_file_is_refused_with_its_path(tmp_path: Path) -> None:
    with pytest.raises(ManifestError, match="module.yaml"):
        load_manifest(tmp_path / "module.yaml")
