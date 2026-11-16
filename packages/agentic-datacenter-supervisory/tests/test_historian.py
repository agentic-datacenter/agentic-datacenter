"""The historian: energy at 15 min, real-time values at 1 s (SDD 7.5)."""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.supervisory.historian import Historian, default_realtime_tags
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[3]
POD = "cooling.pod[01].supply_air_c"


def system(**options: Any) -> tuple[Kernel, PointDatabase, Historian]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    return kernel, points, Historian(kernel, points, **options)


def test_real_time_values_are_kept_every_second() -> None:
    kernel, points, historian = system()
    assert POD in default_realtime_tags(points) and POD in historian.realtime_tags
    kernel.run_for(10_000)
    samples = historian.history(POD)
    assert [s.time_ms for s in samples] == list(range(0, 10_000, 1000))
    assert all(s.quality == "good" and 15.0 < float(s.value) < 30.0 for s in samples)
    assert [s.time_ms for s in historian.history(POD, from_ms=4000, to_ms=6000)] == [
        4000, 5000, 6000,
    ]  # fmt: skip


def test_real_time_retention_is_configurable() -> None:
    kernel, _, historian = system(retention_s=30)
    kernel.run_for(60_000)
    samples = historian.history(POD)
    assert len(samples) == 30 and samples[0].time_ms == 30_000 and samples[-1].time_ms == 59_000


def test_a_stale_value_is_recorded_as_stale() -> None:
    kernel, points, historian = system()
    kernel.run_for(2000)
    points.set_link(False)
    kernel.run_for(6000)
    assert historian.history(POD)[-1].quality == "stale"


def test_energy_is_recorded_every_fifteen_minutes() -> None:
    kernel, _, historian = system()
    kernel.run_for(31 * 60_000)
    records = historian.energy_records()
    assert [r["time_ms"] for r in records] == [900_000, 1_800_000]
    for record in records:
        assert record["interval_s"] == 900 and record["quality"] == "good"
        assert 0.0 < record["it_kwh"] < record["facility_kwh"]
        assert record["pue"] == pytest.approx(record["facility_kwh"] / record["it_kwh"])
    # 2,400 kW of IT load at the design point is 600 kWh in a quarter of an hour.
    assert records[1]["it_kwh"] == pytest.approx(600.0, rel=0.25)


def test_unknown_tag_is_refused() -> None:
    _, _, historian = system()
    with pytest.raises(KeyError, match="not recorded"):
        historian.history("cooling.pod[01].no_such_point")


def test_history_is_cut_back_when_the_run_is_restored_to_an_earlier_time() -> None:
    kernel, _, historian = system()
    kernel.run_for(5000)
    saved = kernel.snapshot()
    kernel.run_for(5000)
    first = historian.history(POD)
    kernel.restore(saved)
    kernel.run_for(5000)
    assert historian.history(POD) == first, "one sample per second, none twice"


def test_historian_is_not_part_of_the_state_hash() -> None:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    PointDatabase(kernel, plant)
    kernel.run_for(5000)
    other_kernel, _, _ = system()
    other_kernel.run_for(5000)
    assert other_kernel.state_hash() == kernel.state_hash()
