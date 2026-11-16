"""The governed branch of a what-if on REMORA's execution service (ADR 0019, ADC-WIF-002)."""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.whatif.models import parse_spec
from agentic_datacenter.whatif.runner import WhatIfResult, run_whatif

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
HOUR_MS = 3_600_000


def governed_gate(library: ContractLibrary) -> Any:
    from agentic_datacenter_remora.governed import GovernedRemoraGate

    return GovernedRemoraGate(library, verify_pin=False)


@pytest.fixture(scope="module")
def result() -> WhatIfResult:
    pytest.importorskip("remora")
    spec = parse_spec({
        "scenario": "WF-01", "duration_s": 3 * 3600, "branches": ["baseline", "governed"],
        "change": {"contract_id": "chw.set_supply_setpoint.v1", "argument": "setpoint_c",
                   "target": 20.5, "expected_start": 18.0},
        "policy": {"enabled": False},
    })  # fmt: skip
    return run_whatif(spec, PROFILE, CONTRACTS, gates={"remora_governed": governed_gate})


@pytest.mark.req("ADC-WIF-002")
def test_the_governed_branch_runs_under_remora_and_stays_inside_the_contract(
    result: WhatIfResult,
) -> None:
    governed = result.branches["governed"]
    assert governed.gate == "remora_governed" and governed.operating_profile == "GOVERNED"
    assert governed.run is not None and governed.governance is not None
    assert all(v == 0 for v in governed.governance.values())
    done = [r for r in governed.run.records if r["outcome"] == "APPLIED"]
    assert done and all(str(r["decision_ref"]) for r in done)
    assert all(any("remora:" in str(x) for x in r["reasons"]) for r in done)
    times = [int(str(r["time_ms"])) for r in done]
    for t in times:
        assert sum(1 for u in times if t - HOUR_MS < u <= t) <= 2
    assert sum(abs(float(r["writes"][0][1]) - float(r["writes"][0][2])) for r in done) <= 2.0
    assert result.start_state_hashes["governed"] == result.start_state_hashes["baseline"]


@pytest.mark.req("ADC-WIF-002")
def test_it_says_how_far_it_got_and_why_it_stopped(result: WhatIfResult) -> None:
    outcome = result.branches["governed"].outcome
    assert outcome is not None and outcome["reached"] is False
    assert outcome["final_value"] == pytest.approx(20.0)
    assert any("cumulative" in reason for reason in outcome["stopped_because"])
    assert outcome["remora_reasons"], "REMORA's own reasons are carried"
    evidence = result.branches["governed"].run
    assert evidence is not None and evidence.gate_evidence is not None
