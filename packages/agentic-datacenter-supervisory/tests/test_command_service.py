"""Point database and Supervisory Command Service (ADC-SUP-003, -005, ADC-GOV-002)."""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.supervisory.command_service import Actor, CommandService
from agentic_datacenter.supervisory.points import PointDatabase

REPO = Path(__file__).resolve().parents[3]
OPERATOR = Actor("ola", "operator")
ENGINEER = Actor("eva", "engineer")
VIEWER = Actor("vik", "viewer")
AGENT = Actor("agent-1", "agent")
CHWS = "cooling.chw_plant[CHW].chws_sp_c"
POD_SP = "cooling.pod[01].supply_air_sp_c"
TDEN = "electrical.power_train[A].tden_s"
BREAKER_CMD = "electrical.power_train[A].gen_brk_close_cmd"
TEST_START = "electrical.genset[A].test_start_request"


def system() -> tuple[Kernel, Any, PointDatabase, CommandService]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    service = CommandService(kernel, points)
    kernel.run_for(5000)
    return kernel, plant, points, service


# --- point database ---------------------------------------------------------------


def test_every_module_point_is_in_the_database_with_its_declaration() -> None:
    _, plant, points, _ = system()
    record = points.read(CHWS)
    assert (record.value, record.unit, record.tier, record.quality) == (18.0, "degC", "T3", "good")
    assert record.kind == "analog_setting" and record.range == (16.0, 21.0)
    assert len(points.tags()) == len(set(points.tags())) >= 700
    assert len(points.find("cooling.pod", "supply_air_c")) == 16


def test_unknown_tag_is_refused() -> None:
    _, _, points, _ = system()
    with pytest.raises(KeyError, match="no.such"):
        points.read("no.such[X].point")


def test_values_go_stale_after_three_missed_polls_and_recover() -> None:
    kernel, plant, points, _ = system()
    pod = plant.module("cooling.pod", "01")
    points.set_link(False)
    kernel.run_for(2000)
    assert points.read(POD_SP).quality == "good", "two missed polls are not yet stale"
    pod.io["supply_air_sp_c"] = 23.0
    kernel.run_for(2000)
    record = points.read(POD_SP)
    assert record.quality == "stale" and record.value == 22.0, "the last value that was polled"
    assert record.time_ms <= 5000
    points.set_link(True)
    kernel.run_for(1000)
    assert points.read(POD_SP).quality == "good" and points.read(POD_SP).value == 23.0


# --- command service ----------------------------------------------------------------


@pytest.mark.req("ADC-SUP-003")
def test_accepted_write_changes_the_point_and_is_logged_in_full() -> None:
    kernel, plant, points, service = system()
    result = service.write(CHWS, 19.0, OPERATOR, reason="trim for part load")
    assert result.accepted and result.code == "OK"
    kernel.run_for(1000)
    assert plant.module("cooling.chw_plant", "CHW").io["chws_sp_c"] == 19.0
    entry = service.change_log()[-1]
    assert entry == {
        "seq": 0, "time_ms": 5000, "tag": CHWS, "old": 18.0, "new": 19.0,
        "actor": "ola", "role": "operator", "reason": "trim for part load",
        "decision_ref": None, "accepted": True, "code": "OK",
    }  # fmt: skip


@pytest.mark.req("ADC-SUP-005")
@pytest.mark.parametrize(
    ("tag", "value", "actor", "code"),
    [
        ("no.such[X].point", 1.0, OPERATOR, "UNKNOWN_TAG"),
        (BREAKER_CMD, True, ENGINEER, "TIER_FORBIDDEN"),
        (TDEN, 10.0, ENGINEER, "TIER_FORBIDDEN"),
        (CHWS, 19.0, VIEWER, "ROLE_FORBIDDEN"),
        (CHWS, 25.0, OPERATOR, "OUT_OF_RANGE"),
        (CHWS, "warm", OPERATOR, "OUT_OF_RANGE"),
        (CHWS, 19.0, AGENT, "DECISION_REQUIRED"),
        (TEST_START, True, AGENT, "DECISION_REQUIRED"),
    ],
)
def test_refused_write_has_a_distinct_reason_code_and_changes_nothing(
    tag: str, value: Any, actor: Actor, code: str
) -> None:
    _, _, points, service = system()
    before = points.read(tag).value if tag in points.tags() else None
    result = service.write(tag, value, actor, reason="test")
    assert not result.accepted and result.code == code
    if before is not None:
        assert points.read(tag).value == before
    assert service.change_log()[-1]["accepted"] is False
    assert service.change_log()[-1]["code"] == code


@pytest.mark.req("ADC-SUP-005")
def test_write_needs_a_reason() -> None:
    _, _, _, service = system()
    assert service.write(CHWS, 19.0, OPERATOR, reason="  ").code == "REASON_REQUIRED"


@pytest.mark.req("ADC-SUP-005")
def test_write_is_refused_while_the_supervisory_network_is_down() -> None:
    _, _, points, service = system()
    points.set_link(False)
    assert service.write(CHWS, 19.0, OPERATOR, reason="x").code == "LINK_DOWN"


@pytest.mark.req("ADC-SUP-005")
def test_writes_are_rate_limited_per_actor() -> None:
    kernel, _, _, service = system()
    codes = [
        service.write(POD_SP, 22.0 + 0.1 * (k % 5), OPERATOR, reason="x").code for k in range(12)
    ]
    assert codes[:10] == ["OK"] * 10 and codes[10:] == ["RATE_LIMITED"] * 2
    assert service.write(POD_SP, 22.5, ENGINEER, reason="x").code == "OK", "another actor"
    kernel.run_for(60_000)
    assert service.write(POD_SP, 22.5, OPERATOR, reason="x").code == "OK", "a minute later"


@pytest.mark.req("ADC-SUP-005")
def test_operator_may_write_tier_two_points() -> None:
    kernel, plant, _, service = system()
    assert service.write(TEST_START, True, OPERATOR, reason="monthly test").accepted
    kernel.run_for(15_000)
    assert plant.module("electrical.genset", "A").io["state"] == "READY_TO_LOAD"


@pytest.mark.req("ADC-SUP-002")
def test_change_log_cannot_be_modified_through_what_it_returns() -> None:
    _, _, _, service = system()
    service.write(CHWS, 19.0, OPERATOR, reason="x")
    log = service.change_log()
    log[0]["actor"] = "nobody"
    log.clear()
    assert service.change_log()[0]["actor"] == "ola"


# --- decision references ---------------------------------------------------------------


@pytest.mark.req("ADC-GOV-002")
def test_agent_write_with_a_valid_decision_reference_is_executed_once() -> None:
    kernel, _, points, service = system()
    service.authorize("dec-1", CHWS, 18.5, expires_ms=kernel.clock.now_ms + 60_000)
    first = service.write(CHWS, 18.5, AGENT, reason="contract chw.raise", decision_ref="dec-1")
    assert first.accepted and points.read(CHWS).value == 18.5
    assert service.change_log()[-1]["decision_ref"] == "dec-1"
    again = service.write(CHWS, 18.5, AGENT, reason="replay", decision_ref="dec-1")
    assert again.code == "DECISION_USED"


@pytest.mark.req("ADC-GOV-002")
@pytest.mark.parametrize(
    ("tag", "value", "wait_ms", "ref", "code"),
    [
        (CHWS, 18.5, 0, "dec-unknown", "DECISION_UNKNOWN"),
        (CHWS, 19.0, 0, "dec-1", "DECISION_MISMATCH"),
        (POD_SP, 18.5, 0, "dec-1", "DECISION_MISMATCH"),
        (CHWS, 18.5, 61_000, "dec-1", "DECISION_EXPIRED"),
    ],
)
def test_decision_reference_must_be_known_unexpired_and_match_tag_and_value(
    tag: str, value: float, wait_ms: int, ref: str, code: str
) -> None:
    kernel, _, points, service = system()
    service.authorize("dec-1", CHWS, 18.5, expires_ms=kernel.clock.now_ms + 60_000)
    kernel.run_for(wait_ms)
    result = service.write(tag, value, AGENT, reason="x", decision_ref=ref)
    assert not result.accepted and result.code == code
    assert points.read(CHWS).value == 18.0


@pytest.mark.req("ADC-GOV-002")
def test_decision_reference_does_not_lift_tier_range_or_rate_checks() -> None:
    kernel, _, _, service = system()
    later = kernel.clock.now_ms + 60_000
    service.authorize("dec-t1", TDEN, 10.0, expires_ms=later)
    assert (
        service.write(TDEN, 10.0, AGENT, reason="x", decision_ref="dec-t1").code == "TIER_FORBIDDEN"
    )
    service.authorize("dec-range", CHWS, 25.0, expires_ms=later)
    assert (
        service.write(CHWS, 25.0, AGENT, reason="x", decision_ref="dec-range").code
        == "OUT_OF_RANGE"
    )


def test_state_of_the_service_is_part_of_the_simulator_state() -> None:
    kernel, _, _, service = system()
    before = kernel.state_hash()
    service.write(CHWS, 19.0, OPERATOR, reason="x")
    assert kernel.state_hash() != before
    saved = kernel.snapshot()
    service.write(CHWS, 20.0, OPERATOR, reason="y")
    kernel.restore(saved)
    assert len(service.change_log()) == 1


# --- overview -------------------------------------------------------------------------


def test_overview_reports_redundancy_alarms_and_energy() -> None:
    from agentic_datacenter.supervisory.overview import N_PLUS_1, Overview

    kernel, plant, points, _ = system()
    view = Overview(points)
    kernel.run_for(600_000)
    margin = view.redundancy()
    assert margin["chillers"].level == N_PLUS_1 and margin["chillers"].level_name == "N_PLUS_1"
    assert (margin["chillers"].available, margin["chillers"].required) == (3, 2)
    assert margin["pumps"].level == N_PLUS_1 and margin["trains"].level == N_PLUS_1
    assert view.active_alarms() == []
    energy = view.energy()
    assert energy["it_kw"] == pytest.approx(2400.0, rel=0.01)
    assert 1.2 < float(energy["pue"]) < 1.4 and energy["quality"] == "good"

    plant.module("cooling.chw_plant", "CHW").inject("chiller_trip", chiller=1)
    kernel.run_for(5000)
    margin = view.redundancy()
    assert margin["chillers"].level_name == "N", "two usable, two needed"
    alarms = view.active_alarms()
    assert [a.system for a in alarms] == ["CHW"] and "Chiller 1" in alarms[0].description

    points.set_link(False)
    kernel.run_for(5000)
    assert view.redundancy()["chillers"].quality == "stale"
    assert view.energy()["quality"] == "stale"
