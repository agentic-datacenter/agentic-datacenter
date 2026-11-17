"""Scenario OP-09: an operator runs it through the API by script."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import ScriptedMaintenance
from agentic_datacenter.scenarios.harness import run_scenario
from agentic_datacenter.scenarios.scenario import load_scenario
from agentic_datacenter.supervisory.api import create_app
from agentic_datacenter.supervisory.sessions import DEFAULT_USERS
from agentic_datacenter.supervisory.station import build_supervisory

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
LEAD = "cooling.chw_plant[CHW].lead_chiller"
TEST = "electrical.genset[A].test_start_request"
GENSET = "electrical.genset[A].state"
MINUTE = 60_000


def test_operator_runs_op09_through_the_api_by_script() -> None:
    kernel = Kernel(seed=1)
    plant = build_plant(PROFILE, kernel, ModuleRegistry.from_entry_points())
    client = TestClient(create_app(build_supervisory(kernel, plant)))
    kernel.run_for(10 * MINUTE)

    def get(path: str) -> Any:
        return client.get(path).json()

    def chillers() -> list[str]:
        return [get(f"/v1/points/cooling.chw_plant[CHW].ch{n}_state")["value"] for n in (1, 2, 3)]

    alarms: list[Any] = []
    hottest = 0.0

    def run(minutes: int) -> None:
        nonlocal hottest
        for _ in range(minutes):
            kernel.run_for(MINUTE)
            alarms.extend(get("/v1/alarms"))
            pods = get("/v1/points?prefix=cooling.pod")
            hottest = max(
                hottest, *(p["value"] for p in pods if p["tag"].endswith(".supply_air_c"))
            )

    secret = DEFAULT_USERS["operator-ola"][1]
    token = client.post("/v1/sessions", json={"user": "operator-ola", "secret": secret}).json()
    headers = {"Authorization": f"Bearer {token['token']}"}

    def command(tag: str, value: Any, reason: str) -> None:
        body = {"tag": tag, "value": value, "reason": reason}
        answer = client.post("/v1/commands", json=body, headers=headers)
        assert answer.status_code == 200, answer.json()

    # Planned lead chiller rotation.
    assert chillers() == ["RUNNING", "RUNNING", "OFF"]
    assert get("/v1/redundancy")["chillers"]["level"] == "N_PLUS_1"
    command(LEAD, "2", "WO-201 planned lead rotation")
    run(10)
    assert chillers() == ["OFF", "RUNNING", "RUNNING"]

    # Monthly generator test: start, run unloaded for ten minutes, stop.
    assert get(f"/v1/points/{GENSET}")["value"] == "STOPPED"
    command(TEST, True, "WO-202 monthly generator test")
    run(10)
    assert get(f"/v1/points/{GENSET}")["value"] == "READY_TO_LOAD"
    assert get("/v1/points/electrical.power_train[A].state")["value"] == "ON_UTILITY"
    command(TEST, False, "WO-202 test complete")
    run(2)
    assert get(f"/v1/points/{GENSET}")["value"] == "STOPPED"

    assert alarms == [], "rotation and test complete without alarms"
    assert hottest < 25.0
    assert get("/v1/redundancy")["chillers"]["level"] == "N_PLUS_1"
    changes = get("/v1/changes")
    assert [(c["tag"], c["new"], c["actor"], c["accepted"]) for c in changes] == [
        (LEAD, "2", "operator-ola", True),
        (TEST, True, "operator-ola", True),
        (TEST, False, "operator-ola", True),
    ]
    assert len(get("/v1/history/energy")) == 2, "two quarter-hour energy records in 32 minutes"


def remora_gate() -> Any:
    pytest.importorskip("remora")
    from agentic_datacenter_remora.binding import RemoraGate

    return RemoraGate()


def test_op09_under_a_gate_is_an_approval_flow_executed_within_bounds() -> None:
    result = run_scenario(
        load_scenario("OP-09"),
        PROFILE,
        remora_gate(),
        "DECISION_ONLY",
        ScriptedMaintenance(),
        1,
        CONTRACTS,
    )
    assert result.passed, result.failed_criteria
    flow = [(r["contract_id"], r["verdict"], r["outcome"]) for r in result.records]
    assert flow == [
        ("chw.rotate_lead_chiller.v1", "VERIFY", "APPLIED"),
        ("genset.start_test_run.v1", "VERIFY", "APPLIED"),
    ]
    for record in result.records:
        approvers = record["approvers"]
        assert isinstance(approvers, list) and "agent-1" not in approvers
        # The contract asks for one operator; REMORA's policy asks for two at this risk tier.
        assert len(approvers) == record["required_approvers"] >= 1
    assert result.metrics.approvals_requested == 2 and result.metrics.alarms_raised == 0
    written = [(c["tag"], c["new"]) for c in result.change_log if c["accepted"]]
    assert written == [(LEAD, "2"), (TEST, True)]


def test_op09_without_a_gate_nobody_is_asked() -> None:
    result = run_scenario(
        load_scenario("OP-09"), PROFILE, NullGate(), "UNGOVERNED", ScriptedMaintenance(), 1,
        CONTRACTS,
    )  # fmt: skip
    assert result.metrics.approvals_requested == 0 and result.metrics.executed == 2


def test_alarms_raised_is_measured_in_a_run() -> None:
    result = run_scenario(
        load_scenario("OP-03"), PROFILE, NullGate(), "BASELINE_RULES", None, 1, CONTRACTS
    )
    assert result.metrics.alarms_raised >= 1, "the tripped chiller"
