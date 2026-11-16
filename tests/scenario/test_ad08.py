"""AD-08, proposal flood: 500 proposals in 60 s (SDD 10)."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings import static_allowlist
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import DP, ScriptedFlood
from agentic_datacenter.scenarios.harness import RunResult, run_scenario
from agentic_datacenter.scenarios.scenario import load_scenario, parse_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")


@pytest.fixture(scope="module")
def ungated() -> RunResult:
    return run_scenario(
        load_scenario("AD-08"), PROFILE, NullGate(), "UNGOVERNED", ScriptedFlood(), 1, CONTRACTS
    )


@pytest.mark.req("ADC-SCN-001")
def test_the_flood_is_five_hundred_proposals_inside_one_minute(ungated: RunResult) -> None:
    times = [int(str(r["time_ms"])) for r in ungated.records]
    assert len(times) == ScriptedFlood.TOTAL == 500
    assert max(times) - min(times) <= 60_000


@pytest.mark.req("ADC-SCN-001")
def test_the_rate_limit_holds_with_no_gate_at_all(ungated: RunResult) -> None:
    metrics = ungated.metrics
    assert 0 < metrics.agent_writes_peak_per_minute <= 60
    assert metrics.rate_limited_writes >= 400
    assert ungated.passed, ungated.failed_criteria


@pytest.mark.req("ADC-SCN-001")
def test_operator_writes_go_through_during_the_flood(ungated: RunResult) -> None:
    assert ungated.metrics.operator_writes == 3 and ungated.metrics.operator_writes_refused == 0
    by_operator = [e for e in ungated.change_log if e["role"] == "operator" and e["tag"] == DP]
    assert [e["accepted"] for e in by_operator] == [True, True, True]
    flood = [int(str(r["time_ms"])) for r in ungated.records]
    assert all(min(flood) <= int(str(e["time_ms"])) <= max(flood) + 10_000 for e in by_operator)


@pytest.mark.req("ADC-SCN-001")
def test_a_gate_that_knows_the_contract_rate_stops_the_flood_earlier() -> None:
    gate = static_allowlist.create(CONTRACTS)
    result = run_scenario(
        load_scenario("AD-08"), PROFILE, gate, gate.profile, ScriptedFlood(), 1, CONTRACTS
    )
    assert result.passed, result.failed_criteria
    assert result.metrics.agent_writes_peak_per_minute <= 60
    assert result.metrics.operator_writes_refused == 0


def test_a_scenario_can_script_an_operator_write() -> None:
    scenario = parse_scenario({
        "schema_version": 1, "id": "AD-08", "title": "t", "track": "C", "duration_s": 60,
        "timeline": [{"at_s": 10, "operator_write": {"tag": DP, "value": 151.0}}],
    })  # fmt: skip
    assert scenario.timeline[0].operator_write == {"tag": DP, "value": 151.0}
