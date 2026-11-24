"""Facility bundles: one's own data center as a directory of files (ADR 0033)."""

import os
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentic_datacenter.core.facility import FacilityError, load_facility
from agentic_datacenter.core.profile import parse_profile

A = {"value": 1.0, "unit": "kW", "assumed": True}


def write(root: Path, name: str, data: Any) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def header(**extra: Any) -> dict[str, Any]:
    return {"schema_version": 2, "name": "my_dc", "site": "DC7", **extra}


def pods_part() -> dict[str, Any]:
    return {
        "key_sets": {"pods": ["01", "02", "03"]},
        "modules": [
            {
                "id": "cooling.pod",
                "for_each": "pods",
                "instance": "{pods}",
                "params": {"fan_kw": {"value": 6.0, "unit": "kW", "assumed": True}},
            }
        ],
    }


def params_of(profile: Any, module_id: str) -> dict[str, dict[str, Any]]:
    return {
        spec.instance: dict(spec.params)
        for spec in profile.instances()
        if spec.module_id == module_id
    }


@pytest.mark.req("ADC-FAC-001")
def test_a_bundle_compiles_to_one_profile_with_the_hash_of_every_file(tmp_path: Path) -> None:
    write(tmp_path, "datacenter.yaml", header(include=["pods/*.yaml"]))
    write(tmp_path, "pods/pods.yaml", pods_part())
    facility = load_facility(tmp_path)
    assert facility.profile.schema_version == 1
    assert facility.profile.name == "my_dc" and facility.profile.site == "DC7"
    assert sorted(params_of(facility.profile, "cooling.pod")) == ["01", "02", "03"]
    assert set(facility.files) == {"datacenter.yaml", "pods/pods.yaml"}
    assert all(len(digest) == 64 for digest in facility.files.values())
    again = load_facility(tmp_path / "datacenter.yaml")
    assert again.profile.hash() == facility.profile.hash()
    assert again.files == facility.files


@pytest.mark.req("ADC-FAC-001")
def test_lists_are_joined_in_include_order_and_a_key_defined_twice_is_refused(
    tmp_path: Path,
) -> None:
    write(tmp_path, "datacenter.yaml", header(include=["b.yaml", "a.yaml"]))
    write(tmp_path, "b.yaml", pods_part())
    write(tmp_path, "a.yaml", {"modules": [{"id": "sensors", "instances": ["SENSORS"]}]})
    ids = [use.id for use in load_facility(tmp_path).profile.module_uses]
    assert ids == ["cooling.pod", "sensors"]
    write(tmp_path, "a.yaml", {"key_sets": {"pods": ["09"]}})
    with pytest.raises(FacilityError, match=r"pods.*b\.yaml.*a\.yaml"):
        load_facility(tmp_path)


@pytest.mark.req("ADC-FAC-001")
@pytest.mark.parametrize(
    "include", ["../outside.yaml", "/etc/hosts", "missing.yaml", "none/*.yaml"]
)
def test_an_include_outside_the_bundle_or_that_names_nothing_is_refused(
    tmp_path: Path, include: str
) -> None:
    bundle = tmp_path / "bundle"
    write(tmp_path, "outside.yaml", pods_part())
    write(bundle, "datacenter.yaml", header(include=[include]))
    with pytest.raises(FacilityError):
        load_facility(bundle)


@pytest.mark.req("ADC-FAC-001")
def test_a_symbolic_link_out_of_the_bundle_is_refused(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    write(tmp_path, "outside.yaml", pods_part())
    write(bundle, "datacenter.yaml", header(include=["link.yaml"]))
    os.symlink(tmp_path / "outside.yaml", bundle / "link.yaml")
    with pytest.raises(FacilityError, match="outside"):
        load_facility(bundle)


@pytest.mark.req("ADC-FAC-001")
def test_too_large_a_file_or_too_many_files_is_refused(tmp_path: Path) -> None:
    write(tmp_path, "datacenter.yaml", header(include=["big.yaml"]))
    (tmp_path / "big.yaml").write_text("# " + "x" * (1024 * 1024), encoding="utf-8")
    with pytest.raises(FacilityError, match="1 MiB"):
        load_facility(tmp_path)
    many = tmp_path / "many"
    write(many, "datacenter.yaml", header(include=["p/*.yaml"]))
    for n in range(256):
        write(many, f"p/{n:03d}.yaml", {})
    with pytest.raises(FacilityError, match="256"):
        load_facility(many)


@pytest.mark.req("ADC-FAC-001")
def test_an_included_file_with_a_key_a_part_may_not_hold_is_refused(tmp_path: Path) -> None:
    write(tmp_path, "datacenter.yaml", header(include=["x.yaml"]))
    write(tmp_path, "x.yaml", {"name": "other"})
    with pytest.raises(FacilityError, match="name"):
        load_facility(tmp_path)


@pytest.mark.req("ADC-FAC-002")
def test_a_schema_1_profile_is_a_facility_of_one_file_with_its_own_hash(tmp_path: Path) -> None:
    data = {"schema_version": 1, "name": "one", "site": "S", **pods_part()}
    path = write(tmp_path, "one.yaml", data)
    facility = load_facility(path)
    assert facility.profile.hash() == parse_profile(data).hash()
    assert list(facility.files) == ["one.yaml"]


@pytest.mark.req("ADC-FAC-002")
def test_a_bundle_without_equipment_or_overrides_lowers_to_the_same_profile(
    tmp_path: Path,
) -> None:
    v1 = {"schema_version": 1, "name": "my_dc", "site": "DC7", **pods_part()}
    write(tmp_path, "datacenter.yaml", header(include=["pods.yaml"]))
    write(tmp_path, "pods.yaml", pods_part())
    assert load_facility(tmp_path).profile.hash() == parse_profile(v1).hash()


EQUIPMENT = {
    "pod_150": {
        "module": "cooling.pod",
        "maker": "Example Cooling",
        "model": "AHU-4x40",
        "evidence": "datasheet rev B",
        "params": {
            "design_it_kw": {"value": 150.0, "unit": "kW", "source": "datasheet rev B, p. 4"},
            "fan_kw": {"value": 7.0, "unit": "kW", "source": "datasheet rev B, p. 5"},
        },
    },
    "pod_300": {
        "module": "cooling.pod",
        "maker": "Example Cooling",
        "model": "AHU-4x80",
        "evidence": "datasheet rev C",
        "params": {"design_it_kw": {"value": 300.0, "unit": "kW", "source": "datasheet rev C"}},
    },
}


def bundle_with(tmp_path: Path, use: dict[str, Any], equipment: Any = EQUIPMENT) -> Path:
    write(tmp_path, "datacenter.yaml", header(include=["pods.yaml", "equipment.yaml"]))
    part = pods_part()
    part["modules"] = [{"id": "cooling.pod", "for_each": "pods", "instance": "{pods}", **use}]
    write(tmp_path, "pods.yaml", part)
    write(tmp_path, "equipment.yaml", {"equipment": equipment})
    return tmp_path


@pytest.mark.req("ADC-FAC-003")
def test_values_resolve_default_equipment_use_then_instance(tmp_path: Path) -> None:
    use = {
        "equipment": "pod_150",
        "params": {"fan_kw": {"value": 8.0, "unit": "kW", "assumed": True}},
        "overrides": {
            "02": {"equipment": "pod_300"},
            "03": {"params": {"fan_kw": {"value": 9.0, "unit": "kW", "source": "survey"}}},
        },
    }
    facility = load_facility(bundle_with(tmp_path, use))
    got = params_of(facility.profile, "cooling.pod")
    assert got["01"] == {"design_it_kw": 150.0, "fan_kw": 8.0}  # the use beats the model
    assert got["02"] == {"design_it_kw": 300.0, "fan_kw": 8.0}  # the instance's model beats both
    assert got["03"] == {"design_it_kw": 150.0, "fan_kw": 9.0}  # the instance's value beats all
    uses = [u for u in facility.profile.module_uses if u.id == "cooling.pod"]
    assert sorted(i for u in uses for i in (u.instances or [])) == ["01", "02", "03"]
    sources = {
        (i, name): p.source or "assumed"
        for u in uses
        for i in u.instances or []
        for name, p in u.params.items()
    }
    assert sources[("01", "design_it_kw")] == "equipment pod_150: datasheet rev B, p. 4"
    assert sources[("02", "design_it_kw")] == "equipment pod_300: datasheet rev C"
    assert sources[("03", "fan_kw")] == "survey"
    assert sources[("01", "fan_kw")] == "assumed"
    assert facility.values == {"sourced": 4, "assumed": 2}


@pytest.mark.req("ADC-FAC-003")
def test_with_param_can_change_one_instance(tmp_path: Path) -> None:
    profile = load_facility(bundle_with(tmp_path, {"equipment": "pod_150"})).profile
    changed = profile.with_param("cooling.pod", "fan_kw", 11.0, instance="02")
    got = params_of(changed, "cooling.pod")
    assert got["02"]["fan_kw"] == 11.0
    assert got["01"]["fan_kw"] == got["03"]["fan_kw"] == 7.0
    every = profile.with_param("cooling.pod", "fan_kw", 12.0)
    assert {p["fan_kw"] for p in params_of(every, "cooling.pod").values()} == {12.0}
    with pytest.raises(ValueError, match="09"):
        profile.with_param("cooling.pod", "fan_kw", 1.0, instance="09")


@pytest.mark.req("ADC-FAC-003")
def test_an_override_for_an_instance_the_use_does_not_have_is_refused(tmp_path: Path) -> None:
    use = {"overrides": {"07": {"params": {"fan_kw": A}}}}
    with pytest.raises(FacilityError, match="07"):
        load_facility(bundle_with(tmp_path, use))


@pytest.mark.req("ADC-FAC-005")
def test_an_equipment_model_names_its_module_maker_model_and_evidence(tmp_path: Path) -> None:
    facility = load_facility(bundle_with(tmp_path, {"equipment": "pod_150"}))
    assert facility.equipment["pod_150"].maker == "Example Cooling"
    assert facility.summary()["equipment"] == {
        "pod_150": {
            "module": "cooling.pod",
            "maker": "Example Cooling",
            "model": "AHU-4x40",
            "evidence": "datasheet rev B",
        }
    }
    missing = {k: v for k, v in EQUIPMENT["pod_150"].items() if k != "evidence"}
    with pytest.raises(FacilityError, match="evidence"):
        load_facility(bundle_with(tmp_path, {"equipment": "pod_150"}, {"pod_150": missing}))


@pytest.mark.req("ADC-FAC-005")
def test_an_equipment_model_of_another_module_or_unknown_is_refused(tmp_path: Path) -> None:
    other = {"ups": {**EQUIPMENT["pod_150"], "module": "electrical.ups"}}
    with pytest.raises(FacilityError, match=r"ups.*electrical\.ups.*cooling\.pod"):
        load_facility(bundle_with(tmp_path, {"equipment": "ups"}, other))
    with pytest.raises(FacilityError, match="nope"):
        load_facility(bundle_with(tmp_path, {"equipment": "nope"}))


@pytest.mark.req("ADC-FAC-005")
def test_the_summary_names_the_facility_its_files_and_its_values(tmp_path: Path) -> None:
    facility = load_facility(bundle_with(tmp_path, {"equipment": "pod_150"}))
    summary = facility.summary()
    assert summary["name"] == "my_dc" and summary["site"] == "DC7"
    assert summary["profile_hash"] == facility.profile.hash()
    assert summary["files"] == facility.files
    assert summary["values"] == {"sourced": 6, "assumed": 0}
