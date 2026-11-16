"""`cooling.weather` with ``source: measured``: a historical series mapped onto simulated time.

The series are synthetic and written by the tests.
"""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.ports import Weather
from agentic_datacenter.data import GapTooLong, HashMismatch, OutsideSeries, write_manifest
from agentic_datacenter.plant.cooling.weather import MODULE as WEATHER

ANCHOR = "2020-07-01T02:00:00Z"


def dataset(directory: Path, values: list[str], humidity: list[str] | None = None) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    header = "time_utc,dry_bulb" + (",rel_humidity" if humidity else "")
    rows = [header]
    for i, value in enumerate(values):
        rows.append(f"2020-07-01T{i:02d}:00:00Z,{value}" + (f",{humidity[i]}" if humidity else ""))
    (directory / "series.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    units = {"dry_bulb": "degC"} | ({"rel_humidity": "%"} if humidity else {})
    return write_manifest(
        directory / "series.csv", dataset_id="synthetic_site", title="test", source="test",
        version="1", licence="none", redistribution="not_cleared", quality_status="synthetic",
        units=units, gap_tolerance_s=3600,
    )  # fmt: skip


def measured(manifest: Path, anchor: str = ANCHOR, **extra: Any) -> dict[str, Any]:
    return {"source": "measured", "manifest": str(manifest), "anchor_utc": anchor, **extra}


VALUES = ["10.0", "12.0", "20.0", "24.0", "30.0", "28.0"]


def test_simulated_time_zero_is_the_anchor(rig: Any, tmp_path: Path) -> None:
    r = rig(WEATHER, measured(dataset(tmp_path, VALUES)))
    assert r.out("ambient").dry_bulb_c == 20.0
    r.run(1.1)
    assert r.out("ambient").dry_bulb_c == pytest.approx(20.0 + 4.0 / 3600)


def test_values_at_and_between_hours_follow_the_series(rig: Any, tmp_path: Path) -> None:
    r = rig(WEATHER, measured(dataset(tmp_path, VALUES)))
    r.run(1800)
    r.run(0.1)  # the slow step at 1800 s has run
    assert r.out("ambient").dry_bulb_c == pytest.approx(22.0)
    r.run(1800)
    assert r.out("ambient").dry_bulb_c == pytest.approx(24.0)
    r.run(3600)
    assert r.out("ambient").dry_bulb_c == pytest.approx(30.0)


def test_humidity_comes_from_the_series_when_it_has_one(rig: Any, tmp_path: Path) -> None:
    hum = ["50.0", "50.0", "40.0", "60.0", "60.0", "60.0"]
    r = rig(WEATHER, measured(dataset(tmp_path, VALUES, hum)))
    r.run(1800.1)
    assert r.out("ambient").rel_humidity_pct == pytest.approx(50.0)


def test_humidity_falls_back_to_the_profile_value(rig: Any, tmp_path: Path) -> None:
    r = rig(WEATHER, measured(dataset(tmp_path, VALUES), rel_humidity_pct=35.0))
    assert r.out("ambient") == Weather(dry_bulb_c=20.0, rel_humidity_pct=35.0)


def test_a_scenario_input_still_overrides_and_clear_returns_to_the_series(
    rig: Any, tmp_path: Path
) -> None:
    r = rig(WEATHER, measured(dataset(tmp_path, VALUES)))
    r.module.inject("set", dry_bulb_c=35.0)
    r.run(1)
    assert r.out("ambient").dry_bulb_c == 35.0
    r.module.inject("clear")
    assert r.out("ambient").dry_bulb_c == pytest.approx(20.0 + 4.0 / 3600)


def test_running_past_the_end_of_the_series_fails(rig: Any, tmp_path: Path) -> None:
    r = rig(WEATHER, measured(dataset(tmp_path, VALUES)))
    r.run(3 * 3600 + 0.1)
    assert r.out("ambient").dry_bulb_c == 28.0
    with pytest.raises(OutsideSeries, match="after the series ends"):
        r.run(1)


def test_an_anchor_outside_the_series_fails_at_construction(rig: Any, tmp_path: Path) -> None:
    with pytest.raises(OutsideSeries, match="before the series starts"):
        rig(WEATHER, measured(dataset(tmp_path, VALUES), anchor="2020-06-30T23:00:00Z"))


def test_an_anchor_without_utc_designator_fails(rig: Any, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="UTC"):
        rig(WEATHER, measured(dataset(tmp_path, VALUES), anchor="2020-07-01T02:00:00"))


def test_a_gap_beyond_the_tolerance_fails_when_reached(rig: Any, tmp_path: Path) -> None:
    r = rig(WEATHER, measured(dataset(tmp_path, ["10.0", "12.0", "20.0", "", "", "28.0"])))
    with pytest.raises(GapTooLong, match="dry_bulb"):
        r.run(2)


def test_a_changed_file_is_refused(rig: Any, tmp_path: Path) -> None:
    manifest = dataset(tmp_path, VALUES)
    (tmp_path / "series.csv").write_text("time_utc,dry_bulb\n", encoding="utf-8")
    with pytest.raises(HashMismatch):
        rig(WEATHER, measured(manifest))


def test_measured_mode_needs_a_manifest_and_an_anchor(rig: Any) -> None:
    with pytest.raises(ValueError, match="manifest"):
        rig(WEATHER, {"source": "measured", "anchor_utc": ANCHOR})
    with pytest.raises(ValueError, match="anchor_utc"):
        rig(WEATHER, {"source": "measured", "manifest": "x.json"})


def test_an_unknown_source_is_refused(rig: Any) -> None:
    with pytest.raises(ValueError, match="source"):
        rig(WEATHER, {"source": "forecast"})


def test_the_snapshot_names_the_dataset_and_restores(rig: Any, tmp_path: Path) -> None:
    r = rig(WEATHER, measured(dataset(tmp_path, VALUES)))
    r.run(600)
    state = r.module.snapshot()
    assert state["series"][1] == ANCHOR
    other = rig(WEATHER, measured(dataset(tmp_path / "b", VALUES)))
    other.module.restore(state)
    assert other.module.snapshot() == state


def test_the_synthetic_default_has_no_series_in_its_snapshot(rig: Any) -> None:
    r = rig(WEATHER, {"dry_bulb_c": 20.0})
    assert "series" not in r.module.snapshot()
