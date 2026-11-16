"""Facility profiles: schema, provenance tags, expansion and hash."""

import copy
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentic_datacenter.core.profile import ProfileError, load_profile, parse_profile

BASE: dict[str, Any] = {
    "schema_version": 1,
    "name": "tiny",
    "description": "Two trains, one load each.",
    "site": "DC1",
    "key_sets": {"trains": ["A", "B"]},
    "modules": [
        {"id": "test.source", "instances": ["S1"]},
        {
            "id": "test.load",
            "for_each": "trains",
            "instance": "L-{trains}",
            "params": {"kw": {"value": 150.0, "unit": "kW", "assumed": True}},
        },
    ],
    "connections": [
        {
            "consumer": "test.load[L-{trains}].feed",
            "provider": "test.source[S1].out",
            "for_each": "trains",
        }
    ],
}


def changed(path: str, value: Any) -> dict[str, Any]:
    data = copy.deepcopy(BASE)
    node: Any = data
    *parents, last = path.split("/")
    for part in parents:
        node = node[int(part)] if isinstance(node, list) else node[part]
    if value is ...:
        del node[last]
    elif isinstance(node, list):
        node[int(last)] = value
    else:
        node[last] = value
    return data


def test_profile_expands_instances_and_connections_over_a_key_set() -> None:
    profile = parse_profile(BASE)
    assert [(i.module_id, i.instance) for i in profile.instances()] == [
        ("test.source", "S1"), ("test.load", "L-A"), ("test.load", "L-B"),
    ]  # fmt: skip
    assert [(c.consumer, c.provider) for c in profile.connections()] == [
        ("test.load[L-A].feed", "test.source[S1].out"),
        ("test.load[L-B].feed", "test.source[S1].out"),
    ]


def test_instances_receive_plain_parameter_values_and_all_key_sets() -> None:
    load = parse_profile(BASE).instances()[1]
    assert load.params == {"kw": 150.0}
    assert load.keys == {"trains": ("A", "B")}


def test_connection_rows_substitute_several_names_at_once() -> None:
    data = changed("connections/0", {
        "consumer": "test.load[L-{t}].feed",
        "provider": "test.source[{s}].out",
        "with": [{"t": "A", "s": "S1"}, {"t": "B", "s": "S1"}],
    })  # fmt: skip
    assert len(parse_profile(data).connections()) == 2


@pytest.mark.req("ADC-PRV-004")
@pytest.mark.parametrize(
    "param",
    [
        {"value": 150.0, "unit": "kW"},
        {"value": 150.0, "unit": "kW", "assumed": False},
        {"value": 150.0, "unit": "kW", "assumed": True, "source": "vendor datasheet"},
        {"value": 150.0, "unit": "kW", "source": ""},
        150.0,
    ],
)
def test_parameter_without_exactly_one_provenance_tag_is_refused(param: Any) -> None:
    with pytest.raises(ProfileError, match="kw"):
        parse_profile(changed("modules/1/params/kw", param))


@pytest.mark.req("ADC-PRV-004")
def test_parameter_with_a_source_is_accepted() -> None:
    data = changed("modules/1/params/kw", {"value": 150.0, "unit": "kW", "source": "datasheet X"})
    assert parse_profile(data).instances()[1].params == {"kw": 150.0}


@pytest.mark.parametrize(
    ("path", "value", "message"),
    [
        ("schema_version", 2, "schema_version"),
        ("schema_version", ..., "schema_version"),
        ("colour", "blue", "colour"),
        ("modules/1/for_each", "pods", "pods"),
        ("connections/0/for_each", "pods", "pods"),
        ("connections/0/consumer", "test.load[L-{nothing}].feed", "nothing"),
        ("modules/0/instances", [], "instances"),
        ("modules/0/instances", ["S1", "S1"], "S1"),
        ("key_sets/trains", ["A", "A"], "trains"),
        ("name", "Not A Slug", "name"),
    ],
)
def test_invalid_profile_is_refused_and_names_the_problem(
    path: str, value: Any, message: str
) -> None:
    with pytest.raises(ProfileError, match=message):
        parse_profile(changed(path, value))


def test_module_entry_needs_exactly_one_way_to_name_its_instances() -> None:
    with pytest.raises(ProfileError, match="instances"):
        parse_profile(changed("modules/0/for_each", "trains"))


def test_economics_block_is_empty_unless_the_profile_supplies_it() -> None:
    assert parse_profile(BASE).economics == {}


def test_hash_ignores_key_order_and_changes_with_any_value() -> None:
    reordered = dict(reversed(list(BASE.items())))
    assert parse_profile(BASE).hash() == parse_profile(reordered).hash()
    other = changed("modules/1/params/kw", {"value": 151.0, "unit": "kW", "assumed": True})
    assert parse_profile(BASE).hash() != parse_profile(other).hash()


def test_profile_is_read_from_a_yaml_file(tmp_path: Path) -> None:
    path = tmp_path / "tiny.yaml"
    path.write_text(yaml.safe_dump(BASE), encoding="utf-8")
    assert load_profile(path).name == "tiny"


def test_unreadable_file_is_refused_with_its_path(tmp_path: Path) -> None:
    with pytest.raises(ProfileError, match="missing.yaml"):
        load_profile(tmp_path / "missing.yaml")
