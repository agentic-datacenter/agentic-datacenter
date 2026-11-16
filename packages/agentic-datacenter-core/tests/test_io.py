"""Module I/O points: what a controller can see and touch (ADC-MOD-003)."""

from pathlib import Path
from typing import Any

import pytest
import yaml

from agentic_datacenter.core.io import IOBoard, PointError, load_points, parse_points

POINTS: list[dict[str, Any]] = [
    {"name": "bus_v_pu", "kind": "analog_in", "unit": "pu", "range": [0, 2], "default": 0.0,
     "tier": "T0", "description": "Bus voltage", "assumed": True},
    {"name": "tden_s", "kind": "analog_setting", "unit": "s", "range": [0, 1800], "default": 20.0,
     "step": 0.5, "tier": "T1", "description": "Return delay", "source": "datasheet"},
    {"name": "breaker_closed", "kind": "binary_in", "default": False, "tier": "T0",
     "description": "Breaker feedback", "assumed": True},
    {"name": "close_cmd", "kind": "binary_cmd", "default": False, "tier": "T0",
     "description": "Close command", "assumed": True},
    {"name": "mode", "kind": "enum_status", "values": ["AUTO", "MANUAL", "DISABLE"],
     "default": "AUTO", "tier": "T1", "description": "Mode switch", "assumed": True},
    {"name": "transfers", "kind": "counter", "default": 0, "tier": "T0",
     "description": "Transfer count", "assumed": True},
]  # fmt: skip


def board() -> IOBoard:
    return IOBoard(parse_points(POINTS))


def test_points_start_at_their_defaults() -> None:
    io = board()
    assert io["tden_s"] == 20.0 and io["mode"] == "AUTO" and io["breaker_closed"] is False


def test_declared_point_can_be_written_and_read() -> None:
    io = board()
    io["bus_v_pu"] = 0.97
    io["close_cmd"] = True
    io["mode"] = "MANUAL"
    assert (io["bus_v_pu"], io["close_cmd"], io["mode"]) == (0.97, True, "MANUAL")


@pytest.mark.req("ADC-MOD-003")
def test_undeclared_point_cannot_be_read_or_written() -> None:
    io = board()
    with pytest.raises(PointError, match="chiller_trip"):
        _ = io["chiller_trip"]
    with pytest.raises(PointError, match="chiller_trip"):
        io["chiller_trip"] = True


@pytest.mark.parametrize(
    ("name", "value"),
    [("bus_v_pu", 2.5), ("tden_s", -1.0), ("tden_s", 20.3), ("close_cmd", 1), ("mode", "TEST"),
     ("transfers", -1), ("transfers", 1.5), ("bus_v_pu", "high"), ("bus_v_pu", float("nan"))],
)  # fmt: skip
def test_value_outside_the_declaration_is_refused(name: str, value: Any) -> None:
    with pytest.raises(PointError, match=name):
        board()[name] = value


def test_setting_accepts_a_multiple_of_its_step() -> None:
    io = board()
    io["tden_s"] = 20.5
    assert io["tden_s"] == 20.5


def test_snapshot_and_restore_round_trip() -> None:
    io = board()
    io["bus_v_pu"], io["transfers"] = 0.5, 3
    saved = io.snapshot()
    io["bus_v_pu"], io["transfers"] = 1.0, 4
    io.restore(saved)
    assert (io["bus_v_pu"], io["transfers"]) == (0.5, 3)


@pytest.mark.parametrize(
    ("index", "field", "value", "message"),
    [
        (0, "assumed", ..., "bus_v_pu"),
        (1, "assumed", True, "tden_s"),
        (0, "tier", "T9", "tier"),
        (0, "kind", "analog_out", "kind"),
        (4, "values", ..., "mode"),
        (0, "default", 5.0, "bus_v_pu"),
        (0, "name", "Bus-V", "name"),
        (3, "name", "bus_v_pu", "bus_v_pu"),
    ],
)
def test_invalid_declaration_is_refused(index: int, field: str, value: Any, message: str) -> None:
    import copy

    points = copy.deepcopy(POINTS)
    if value is ...:
        del points[index][field]
    else:
        points[index][field] = value
    with pytest.raises(PointError, match=message):
        parse_points(points)


def test_points_are_read_from_a_yaml_file(tmp_path: Path) -> None:
    path = tmp_path / "points.yaml"
    path.write_text(yaml.safe_dump(POINTS), encoding="utf-8")
    assert [p.name for p in load_points(path)][:2] == ["bus_v_pu", "tden_s"]
