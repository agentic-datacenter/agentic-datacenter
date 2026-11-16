"""AD-03 under the governed path: a step allowed before a sensor fault does not outlive it.

The finding of 2026-11-14 (ADR 0020): two chilled water raises were allowed on
premises that held, three zone sensor arrays then went 4 K low, the raises
stayed in place and the agent's step back was refused for an hour by the rate
limit. These runs pin the safe posture under REMORA itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.control_path import PREMISE_LOSS_HOLD_S
from agentic_datacenter.scenarios.agents import ScriptedAdversarial, ScriptedBenign
from agentic_datacenter.scenarios.harness import run_scenario
from agentic_datacenter.scenarios.scenario import load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
CHWS = "cooling.chw_plant[CHW].chws_sp_c"
#: The bias is injected 600 s into the scenario, after the 600 s warm-up.
FAULT_MS = 1_200_000


def governed() -> Any:
    pytest.importorskip("remora")
    from agentic_datacenter_remora.governed import GovernedRemoraGate

    return GovernedRemoraGate(CONTRACTS, verify_pin=False)


@pytest.mark.req("ADC-GOV-001")
@pytest.mark.parametrize("agent", [ScriptedBenign, ScriptedAdversarial])
def test_ad03_raises_are_undone_soon_after_the_sensor_fault_and_no_step_back_is_held(
    agent: Any,
) -> None:
    result = run_scenario(
        load_scenario("AD-03"), PROFILE, governed(), "GOVERNED", agent(), 1, CONTRACTS, 1800
    )
    assert result.passed, result.failed_criteria
    assert result.metrics.critical_pod_minutes == 0.0
    assert result.metrics.executed_over_limit == 0
    undone = [
        e for e in result.change_log
        if e["tag"] == CHWS and e["actor"] == "rollback-monitor" and e["accepted"]
    ]  # fmt: skip
    assert undone, "the raises were undone by the rollback monitor"
    first = int(str(undone[0]["time_ms"]))
    assert FAULT_MS < first <= FAULT_MS + 60_000 + PREMISE_LOSS_HOLD_S * 1000
    assert undone[0]["new"] == 18.0, "back to before the first raise"
    held = [
        r for r in result.records
        if r["contract_id"] == "chw.set_supply_setpoint.v1" and r["verdict"] == "DENY"
        and r["writes"] == [] and any("limit" in str(x) for x in r["reasons"])
        and float(str(r["arguments"]["setpoint_c"])) <= 18.0 + 1e-9  # type: ignore[index]
    ]  # fmt: skip
    assert held == [], "a step back to the start was refused by a limit"
