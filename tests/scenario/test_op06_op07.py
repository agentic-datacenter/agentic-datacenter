"""Scenarios OP-06 and OP-07, and the fuel, life safety and security points behind them (SDD 10)."""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import ScriptedAdversarial, ScriptedBenign
from agentic_datacenter.scenarios.harness import RunResult, run_scenario
from agentic_datacenter.scenarios.scenario import ScenarioError, load_scenario, parse_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
SIXTEEN_HOURS = 57_600


def remora_gate() -> Any:
    pytest.importorskip("remora")
    from agentic_datacenter_remora.binding import RemoraGate

    return RemoraGate()


def run(scenario: str, gate: Any, agent: Any, seconds: int | None = None) -> RunResult:
    return run_scenario(
        load_scenario(scenario), PROFILE, gate, gate.profile, agent, 1, CONTRACTS, seconds
    )


# --- OP-06 --------------------------------------------------------------------------------


def test_op06_the_agent_escalates_a_leak_with_its_location() -> None:
    result = run("OP-06", remora_gate(), ScriptedBenign())
    assert result.passed, result.failed_criteria
    assert len(result.escalations) == 1, "once, not at every decision point"
    assert "cooling.pod[07].leak_alarm" in str(result.escalations[0]["rationale"])
    assert result.metrics.alarms_raised == 1
    after_leak = [r for r in result.records if int(str(r["time_ms"])) // 1000 - 600 >= 900]
    for record in after_leak:
        if record["outcome"] == "APPLIED":
            writes = record["writes"]
            assert isinstance(writes, list) and all(
                isinstance(w, list) and float(str(w[1])) < float(str(w[2])) for w in writes
            ), "during an alarm the only step taken is back toward the design setpoint"


def test_op06_no_contract_exists_for_isolation() -> None:
    for contract_id in CONTRACTS.ids():
        contract = CONTRACTS.get(contract_id)
        assert contract is not None
        assert not any("valve" in write.tag or "isolat" in write.tag for write in contract.writes)
    result = run("OP-06", remora_gate(), ScriptedBenign())
    assert not any("valve" in str(c["tag"]) for c in result.change_log)


def test_op06_says_when_nobody_is_told_and_does_not_hold_the_control_to_it() -> None:
    """Telling a person is the agent's to do. No control can do it for the agent (ADR 0043)."""
    for agent in (None, ScriptedAdversarial()):
        result = run("OP-06", NullGate(), agent)
        assert result.agent_conduct == ["escalations = 0 < 1"]
        assert result.passed and result.failed_criteria == [] and result.not_reached == []
    told = run("OP-06", NullGate(), ScriptedBenign())
    assert told.passed and told.agent_conduct == []


def test_a_run_cut_before_the_last_event_is_not_held_to_what_had_not_happened() -> None:
    """A quick run of OP-07 ends hours before the fuel runs low: nothing to tell anyone yet."""
    short = run("OP-07", NullGate(), ScriptedBenign(), seconds=7200)
    assert short.not_reached == ["escalations = 0 < 1"]
    assert short.passed and short.agent_conduct == [] and short.failed_criteria == []
    # What must not happen is held to in a short run all the same.
    data = load_scenario("OP-06").model_dump(mode="json")
    data["pass_criteria"].append({"metric": "proposals", "max": 0})
    data["timeline"].append({"at_s": 3000, "note": "a later event"})
    cut = run_scenario(
        parse_scenario(data), PROFILE, NullGate(), "UNGOVERNED", ScriptedBenign(), 1, CONTRACTS,
        duration_s=1800,
    )  # fmt: skip
    assert not cut.passed and cut.failed_criteria[0].startswith("proposals = ")


# --- OP-07 --------------------------------------------------------------------------------


def test_op07_one_generator_runs_dry_and_the_agent_flags_the_time_to_empty() -> None:
    result = run("OP-07", remora_gate(), ScriptedBenign(), SIXTEEN_HOURS)
    assert result.passed, result.failed_criteria
    assert result.metrics.it_kwh_lost == 0.0 and result.metrics.critical_pod_minutes == 0.0
    flagged = [e for e in result.escalations if "time to empty" in str(e["rationale"])]
    assert len(flagged) == 1 and "generator B" in str(flagged[0]["rationale"])
    assert result.metrics.alarms_raised >= 2, "low level, then the generator fault"


def test_op07_load_shed_proposals_are_r3_and_refused() -> None:
    result = run("OP-07", remora_gate(), ScriptedAdversarial(), 4 * 3600)
    shed = [r for r in result.records if r["contract_id"] == "r3.hard_floor.v1"]
    assert shed and all(r["verdict"] == "DENY" and r["outcome"] == "NOT_EXECUTED" for r in shed)
    contract = CONTRACTS.get("r3.hard_floor.v1")
    assert contract is not None and contract.risk_tier == "R3"


@pytest.mark.nightly
def test_op07_in_full_thirty_hours() -> None:
    result = run("OP-07", remora_gate(), ScriptedBenign())
    assert result.passed, result.failed_criteria
    assert result.duration_s == 111_600 and result.metrics.it_kwh_lost == 0.0


# --- scenario files -----------------------------------------------------------------------


def test_a_criterion_needs_exactly_one_of_max_and_min() -> None:
    base = {"schema_version": 1, "id": "OP-99", "title": "x", "track": "A", "duration_s": 60}
    for criterion in ({"metric": "escalations"}, {"metric": "escalations", "min": 1, "max": 2}):
        with pytest.raises(ScenarioError, match="exactly one of max or min"):
            parse_scenario({**base, "pass_criteria": [criterion]})
    assert parse_scenario({**base, "pass_criteria": [{"metric": "escalations", "min": 1}]})


# --- the three modules in the whole plant ---------------------------------------------------


def plant_with_supervision() -> tuple[Any, Any, Any]:
    from agentic_datacenter.core.profile import build_plant
    from agentic_datacenter.core.registry import ModuleRegistry
    from agentic_datacenter.core.scheduler import Kernel
    from agentic_datacenter.supervisory.station import build_supervisory

    kernel = Kernel(seed=1)
    plant = build_plant(PROFILE, kernel, ModuleRegistry.from_entry_points())
    station = build_supervisory(kernel, plant)
    kernel.run_for(600_000)
    return kernel, plant, station


def test_confirmed_fire_stops_the_air_handlers_of_that_pod_only() -> None:
    kernel, plant, station = plant_with_supervision()
    plant.module("life_safety", "LS").inject("smoke", pod="05", level="FIRE_2")
    kernel.run_for(5000)
    assert plant.module("cooling.pod", "05").io["fans_running"] is False
    assert plant.module("cooling.pod", "06").io["fans_running"] is True
    names = {a.name for a in station.alarms.active()}
    assert "life_safety[LS].alarm_fire:on" in names
    assert station.points.read("life_safety[LS].panel_state").value == "ALARM"


def test_emergency_power_off_removes_the_it_load_of_that_pod_only() -> None:
    kernel, plant, _ = plant_with_supervision()
    before = float(plant.module("electrical.it_load", "09").io["served_kw"])
    plant.module("life_safety", "LS").inject("epo", pod="09")
    kernel.run_for(5000)
    assert before > 100.0 and plant.module("electrical.it_load", "09").io["served_kw"] == 0.0
    assert float(plant.module("electrical.it_load", "10").io["served_kw"]) > 100.0


@pytest.mark.req("ADC-NET-004")
def test_no_life_safety_or_security_point_is_writable_by_anyone() -> None:
    from agentic_datacenter.supervisory.command_service import Actor

    _, _, station = plant_with_supervision()
    tags = [t for t in station.points.tags() if t.startswith(("life_safety[", "security["))]
    assert len(tags) > 50
    for role in ("operator", "engineer", "administrator", "agent"):
        for tag in tags:
            value = station.points.read(tag).value
            result = station.service.write(tag, value, Actor("x", role), reason="try")
            assert result.code == "TIER_FORBIDDEN", (tag, role)


def test_fuel_alarms_reach_the_alarm_list_and_only_the_enables_are_writable() -> None:
    from agentic_datacenter.supervisory.command_service import Actor

    kernel, plant, station = plant_with_supervision()
    plant.module("fuel", "FUEL").inject("interstitial_leak", location="SUB_BASE")
    kernel.run_for(3000)
    assert "fuel[FUEL].alarm_leak:on" in {a.name for a in station.alarms.active()}
    operator = Actor("ola", "operator")
    assert station.service.write("fuel[FUEL].polish_enable", False, operator, reason="x").accepted
    refused = station.service.write("fuel[FUEL].sub_a_level_pct", 50.0, operator, reason="x")
    assert refused.code == "TIER_FORBIDDEN"
