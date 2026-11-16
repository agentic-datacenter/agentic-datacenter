"""The alarm engine (ADC-SUP-001, SDD 7.5)."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.supervisory.alarms import (
    ACTIVE_ACKED,
    ACTIVE_UNACKED,
    INACTIVE_ACKED,
    INACTIVE_UNACKED,
    AlarmDef,
    AlarmEngine,
    band,
    default_alarms,
)
from agentic_datacenter.supervisory.logs import LogIntegrityError
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[3]


@dataclass
class _Record:
    tag: str
    value: Any
    quality: str = "good"
    description: str = ""


@dataclass
class FakePoints:
    """Just enough of the point database for the engine: values a test can set."""

    values: dict[str, Any] = field(default_factory=dict)
    quality: dict[str, str] = field(default_factory=dict)

    def tags(self) -> list[str]:
        return sorted(self.values)

    def read(self, tag: str) -> _Record:
        return _Record(tag, self.values[tag], self.quality.get(tag, "good"))

    def value_and_quality(self, tag: str) -> tuple[Any, str]:
        return self.values[tag], self.quality.get(tag, "good")


def engine(*defs: AlarmDef, **values: Any) -> tuple[Kernel, FakePoints, AlarmEngine]:
    kernel = Kernel(seed=1)
    points = FakePoints({name.replace("__", "."): v for name, v in values.items()})
    return kernel, points, AlarmEngine(kernel, points, defs)  # type: ignore[arg-type]


HIGH_TEMP = AlarmDef("t.high", "t", "high", 600, limit=27.0, deadband=0.5)


@pytest.mark.req("ADC-SUP-001")
def test_priority_bands() -> None:
    assert [band(p) for p in (999, 751, 750, 501, 500, 499, 1)] == [
        "urgent", "urgent", "high", "high", "medium", "event", "event",
    ]  # fmt: skip
    for bad in (0, 1000):
        with pytest.raises(ValueError, match="priority"):
            AlarmDef("x", "t", "high", bad)


@pytest.mark.req("ADC-SUP-001")
def test_the_four_states() -> None:
    kernel, points, alarms = engine(HIGH_TEMP, t=22.0)
    kernel.run_for(1000)
    assert alarms.state("t.high") == INACTIVE_ACKED and alarms.active() == []
    points.values["t"] = 28.0
    kernel.run_for(1000)
    assert alarms.state("t.high") == ACTIVE_UNACKED
    alarms.acknowledge("t.high", "ola")
    assert alarms.state("t.high") == ACTIVE_ACKED
    points.values["t"] = 22.0
    kernel.run_for(1000)
    assert alarms.state("t.high") == INACTIVE_ACKED and alarms.active() == []
    # The other path: it returns to normal before anyone has seen it.
    points.values["t"] = 28.0
    kernel.run_for(1000)
    points.values["t"] = 22.0
    kernel.run_for(1000)
    assert alarms.state("t.high") == INACTIVE_UNACKED
    assert [a.name for a in alarms.active()] == ["t.high"], "still on the list until acknowledged"
    alarms.acknowledge("t.high", "ola")
    assert alarms.state("t.high") == INACTIVE_ACKED
    with pytest.raises(ValueError, match="nothing to acknowledge"):
        alarms.acknowledge("t.high", "ola")
    kinds = [(e["kind"], e["alarm"]) for e in alarms.log.entries()]
    assert kinds == [
        ("raised", "t.high"), ("acknowledged", "t.high"), ("cleared", "t.high"),
        ("raised", "t.high"), ("cleared", "t.high"), ("acknowledged", "t.high"),
    ]  # fmt: skip
    assert alarms.log.entries()[1]["actor"] == "ola"


@pytest.mark.req("ADC-SUP-001")
def test_high_and_low_alarms_have_a_deadband() -> None:
    low = AlarmDef("t.low", "t", "low", 600, limit=15.0, deadband=1.0)
    kernel, points, alarms = engine(HIGH_TEMP, low, t=27.0)
    kernel.run_for(1000)
    assert alarms.active() == [], "at the limit is not above it"
    for value, expected in ((27.1, True), (26.8, True), (26.5, True), (26.4, False)):
        points.values["t"] = value
        kernel.run_for(1000)
        assert (alarms.state("t.high") == ACTIVE_UNACKED) is expected, value
    for value, expected in ((14.9, True), (15.5, True), (16.0, True), (16.1, False)):
        points.values["t"] = value
        kernel.run_for(1000)
        assert (alarms.state("t.low") == ACTIVE_UNACKED) is expected, value


@pytest.mark.req("ADC-SUP-001")
def test_rate_of_change_alarm() -> None:
    rate = AlarmDef("t.rate", "t", "rate", 600, limit=2.0)  # kelvin per minute
    kernel, points, alarms = engine(rate, t=20.0)
    for _ in range(90):  # 1.2 K per minute
        points.values["t"] += 0.02
        kernel.run_for(1000)
    assert alarms.state("t.rate") == INACTIVE_ACKED
    for _ in range(70):  # 3 K per minute
        points.values["t"] += 0.05
        kernel.run_for(1000)
    assert alarms.state("t.rate") == ACTIVE_UNACKED
    for _ in range(70):
        kernel.run_for(1000)
    assert alarms.state("t.rate") == INACTIVE_UNACKED


@pytest.mark.req("ADC-SUP-001")
def test_invalid_signal_alarm() -> None:
    invalid = AlarmDef("t.invalid", "t", "invalid", 600)
    kernel, points, alarms = engine(invalid, HIGH_TEMP, t=30.0)
    kernel.run_for(1000)
    assert alarms.state("t.invalid") == INACTIVE_ACKED and alarms.state("t.high") == ACTIVE_UNACKED
    points.quality["t"] = "bad"
    kernel.run_for(1000)
    assert alarms.state("t.invalid") == ACTIVE_UNACKED
    assert alarms.state("t.high") == INACTIVE_UNACKED, "a limit is not judged on an invalid signal"


@pytest.mark.req("ADC-SUP-001")
def test_suppressed_during_the_start_up_delay_of_the_equipment() -> None:
    low_flow = AlarmDef(
        "flow.low", "flow", "low", 600, limit=10.0, running_tag="run", startup_delay_s=30
    )
    kernel, points, alarms = engine(low_flow, flow=0.0, run=False)
    kernel.run_for(5000)
    assert alarms.active() == [], "equipment that is not running has no low-flow alarm"
    points.values["run"] = True
    kernel.run_for(29_000)
    assert alarms.active() == [], "inside the start-up delay"
    kernel.run_for(2000)
    assert alarms.state("flow.low") == ACTIVE_UNACKED
    points.values["run"] = False
    kernel.run_for(1000)
    assert alarms.state("flow.low") == INACTIVE_UNACKED


@pytest.mark.req("ADC-SUP-001")
def test_suppressed_for_equipment_out_of_service() -> None:
    tripped = AlarmDef(
        "ch1.tripped", "state", "discrete", 600, active_values=("TRIPPED",),
        out_of_service=("enable", False),
    )  # fmt: skip
    kernel, points, alarms = engine(tripped, state="TRIPPED", enable=True)
    kernel.run_for(1000)
    assert alarms.state("ch1.tripped") == ACTIVE_UNACKED
    points.values["enable"] = False
    kernel.run_for(1000)
    assert alarms.state("ch1.tripped") == INACTIVE_UNACKED
    assert alarms.log.entries()[-1]["kind"] == "suppressed"
    alarms.acknowledge("ch1.tripped", "ola")
    kernel.run_for(5000)
    assert alarms.active() == []


@pytest.mark.req("ADC-SUP-001")
def test_an_event_is_logged_and_never_listed() -> None:
    started = AlarmDef("gen.started", "running", "discrete", 300)
    kernel, points, alarms = engine(started, running=False)
    points.values["running"] = True
    kernel.run_for(3000)
    assert alarms.active() == []
    events = [e for e in alarms.log.entries() if e["kind"] == "event"]
    assert len(events) == 1 and events[0]["alarm"] == "gen.started"
    with pytest.raises(ValueError, match="nothing to acknowledge"):
        alarms.acknowledge("gen.started", "ola")


@pytest.mark.req("ADC-SUP-001")
def test_active_alarms_are_listed_most_urgent_first() -> None:
    a = AlarmDef("a", "x", "discrete", 600, system="CHW")
    b = AlarmDef("b", "y", "discrete", 900, system="POD")
    kernel, _, alarms = engine(a, b, x=True, y=True)
    kernel.run_for(1000)
    assert [(al.name, al.priority, al.system, al.state) for al in alarms.active()] == [
        ("b", 900, "POD", ACTIVE_UNACKED),
        ("a", 600, "CHW", ACTIVE_UNACKED),
    ]


@pytest.mark.req("ADC-SUP-002")
def test_alarm_log_is_append_only() -> None:
    kernel, _, alarms = engine(AlarmDef("a", "x", "discrete", 600), x=True)
    kernel.run_for(1000)
    with pytest.raises(LogIntegrityError):
        alarms.log.truncate(0, "mallory")
    assert [e["kind"] for e in alarms.log.entries()] == ["raised", "integrity_violation"]


def test_alarm_state_survives_snapshot_and_restore() -> None:
    kernel, points, alarms = engine(HIGH_TEMP, t=28.0)
    kernel.run_for(1000)
    saved, digest = kernel.snapshot(), kernel.state_hash()
    alarms.acknowledge("t.high", "ola")
    assert kernel.state_hash() != digest
    kernel.restore(saved)
    assert alarms.state("t.high") == ACTIVE_UNACKED and kernel.state_hash() == digest
    assert kernel.state.stale_parts() == []


def test_definitions_must_be_unique_and_well_formed() -> None:
    with pytest.raises(ValueError, match="twice"):
        engine(HIGH_TEMP, HIGH_TEMP, t=1.0)
    with pytest.raises(ValueError, match="kind"):
        AlarmDef("x", "t", "sideways", 600)


# --- on the plant --------------------------------------------------------------------------


def plant_engine() -> tuple[Kernel, Any, PointDatabase, AlarmEngine]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    return kernel, plant, points, AlarmEngine(kernel, points, default_alarms(points))


@pytest.mark.req("ADC-SUP-001")
def test_a_healthy_plant_has_no_alarms() -> None:
    kernel, _, _, alarms = plant_engine()
    kernel.run_for(120_000)
    assert alarms.active() == []


@pytest.mark.req("ADC-SUP-001")
def test_a_tripped_chiller_alarms_unless_it_is_out_of_service() -> None:
    kernel, plant, _, alarms = plant_engine()
    kernel.run_for(10_000)
    chw = plant.module("cooling.chw_plant", "CHW")
    chw.inject("chiller_trip", chiller=1)
    kernel.run_for(5000)
    names = [a.name for a in alarms.active()]
    assert "cooling.chw_plant[CHW].ch1_state:fault" in names
    chw.io["ch1_enable"] = False
    kernel.run_for(2000)
    by_name = {a.name: a for a in alarms.active()}
    assert by_name["cooling.chw_plant[CHW].ch1_state:fault"].state == INACTIVE_UNACKED


@pytest.mark.req("ADC-SUP-001")
def test_supervisory_link_loss_raises_invalid_signal_alarms() -> None:
    kernel, _, points, alarms = plant_engine()
    kernel.run_for(5000)
    points.set_link(False)
    kernel.run_for(5000)
    invalid = [a for a in alarms.active() if a.name.endswith(":invalid")]
    assert len(invalid) == 16, "one per POD supply air reading"
