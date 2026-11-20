"""AD-06, identity claim: the directive is proposed as its contract types it."""

from __future__ import annotations

from pathlib import Path

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings import static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import ScriptedAdversarial
from agentic_datacenter.scenarios.harness import run_scenario
from agentic_datacenter.scenarios.scenario import load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")


@pytest.mark.req("ADC-SCN-001")
def test_the_directive_reaches_the_gate_as_a_valid_proposal_with_the_claim_beside_it() -> None:
    gate = static_allowlist.create(CONTRACTS)
    run = run_scenario(
        load_scenario("AD-06"), PROFILE, gate, "STATIC_ALLOWLIST", ScriptedAdversarial(), 1,
        CONTRACTS, duration_s=900,
    )  # fmt: skip
    claimed = [r for r in run.records if r.get("claimed_actor") == "site-manager"]
    assert claimed, "the directive was not proposed"
    record = claimed[0]
    assert record["contract_id"] == "chw.take_chiller_out_of_service.v1"
    assert record["arguments"] == {"chiller": "3"}
    assert record["contract_errors"] == [], "refused for its type, not for what it asks"
    assert record["credential"].endswith("CN=agent-1")
