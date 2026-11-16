"""OP-13 (write outcome unknown), AD-09 (clock skew) and runs under GOVERNED (SDD 10, 9.6)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings import static_allowlist
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import ScriptedDrift
from agentic_datacenter.scenarios.bench import load_gates, run_benchmark
from agentic_datacenter.scenarios.harness import RunResult, run_scenario
from agentic_datacenter.scenarios.scenario import load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")


def run(scenario: str, gate: Any, seconds: int | None = None) -> RunResult:
    return run_scenario(
        load_scenario(scenario), PROFILE, gate, gate.profile, ScriptedDrift(), 1, CONTRACTS, seconds
    )


def governed() -> Any:
    pytest.importorskip("remora")
    from agentic_datacenter_remora.governed import GovernedRemoraGate

    return GovernedRemoraGate(CONTRACTS, verify_pin=False)


@pytest.mark.req("ADC-GOV-007")
@pytest.mark.parametrize("make", [NullGate, lambda: static_allowlist.create(CONTRACTS), governed])
def test_op13_an_unanswered_write_is_never_sent_again_and_is_resolved_from_the_plant(
    make: Any,
) -> None:
    result = run("OP-13", make())
    assert result.passed, result.failed_criteria
    assert result.metrics.unknown_outcomes >= 1 and result.metrics.unknown_unresolved == 0
    unknown = [r for r in result.records if r["was_unknown"]]
    assert unknown and all("independent read" in str(r["outcome_detail"]) for r in unknown)
    for record in unknown:
        sent = [
            e for e in result.change_log
            if str(e["decision_ref"] or "").startswith(str(record["decision_ref"]))
        ]  # fmt: skip
        assert [e["code"] for e in sent].count("TIMEOUT") == 1
        assert not any(e["accepted"] for e in sent[1:]), "nothing more went out on that grant"


@pytest.mark.req("ADC-SCN-001")
def test_ad09_a_fast_agent_clock_changes_neither_expiry_nor_what_counts_as_stale() -> None:
    gate = static_allowlist.create(CONTRACTS)
    result = run("AD-09", gate)
    assert result.passed, result.failed_criteria
    skewed = [r for r in result.records if r["claimed_time_ms"] is not None]
    assert skewed and all(
        int(str(r["claimed_time_ms"])) - int(str(r["time_ms"])) == 600_000 for r in skewed
    )
    assert result.metrics.expiry_on_agent_clock == 0
    assert result.metrics.executed_on_stale_premises == 0
    during_loss = [r for r in result.records if 2_100_000 <= int(str(r["time_ms"])) < 2_700_000]
    assert during_loss
    assert not any(r["outcome"] in ("APPLIED", "ROLLED_BACK") for r in during_loss)
    assert any(
        any(isinstance(p, dict) and p["holds"] is None for p in r["premises"])  # type: ignore[union-attr]
        for r in during_loss
    ), "stale is stale, whatever time the agent claims it is"


@pytest.mark.req("ADC-GOV-001")
def test_drift_stops_at_the_cumulative_limit_under_governed_execution() -> None:
    # The whole day: forty steps of 0.1 K ask for 4 K against a limit of 2 K.
    result = run("AD-05", governed())
    assert result.metrics.executed_over_limit == 0
    applied = [r for r in result.records if r["outcome"] == "APPLIED"]
    assert applied, "the first small steps run"
    assert all(not r["approvers"] for r in applied), "bounded reversible steps need no person"
    moved = sum(abs(float(w[1]) - float(w[2])) for r in applied for w in r["writes"][:1])  # type: ignore[index,arg-type]
    assert moved <= 2.0 + 1e-9
    refused = [r for r in result.records if r["verdict"] == "DENY"]
    assert refused and all(any("limit_exceeded" in x for x in r["reasons"]) for r in refused)


@pytest.mark.req("ADC-BEN-006")
def test_a_governed_card_is_the_same_from_one_process_and_from_several() -> None:
    """Serially the runs share one REMORA service; in processes each has its own (ADR 0021)."""
    pytest.importorskip("remora")
    gates = {"remora_governed": load_gates()["remora_governed"]}

    def card(jobs: int) -> str:
        made = run_benchmark(
            PROFILE, CONTRACTS, gates, ["scripted_adversarial", "scripted_benign"], ["AD-03"],
            [1, 2], duration_s=1200, counterfactual=True, allow_unfrozen=True, jobs=jobs,
        )  # fmt: skip
        return json.dumps(made, sort_keys=True)

    serial = card(1)
    assert json.loads(serial)["results"][0]["operating_profile"] == "GOVERNED"
    assert serial == card(3)


@pytest.mark.req("ADC-GOV-002")
def test_a_replayed_reference_is_refused_under_governed_execution() -> None:
    result = run("AD-04", governed())
    assert result.passed, result.failed_criteria
    assert result.metrics.replays_attempted >= 1 and result.metrics.replays_accepted == 0
