"""The demonstration run: three scenarios, ungoverned against a gate, same seed (SDD 12.2)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.cli import main
from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.envelope_ref import decision_ref
from agentic_datacenter.governance.gate import Decision, Verdict
from agentic_datacenter.scenarios.agents import ScriptedDrift
from agentic_datacenter.scenarios.demo import DEMO_SCENARIOS, build_demo, render_demo, write_demo
from agentic_datacenter.scenarios.harness import run_scenario
from agentic_datacenter.scenarios.scenario import load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")


class LimitGate:
    """A gate that refuses whatever would exceed a rate or cumulative limit."""

    name = "limit_gate"
    profile = "STATIC_ALLOWLIST"

    def evaluate(self, proposal: Any, premises: Any, actor: Any) -> Decision:
        problems = [*premises.schema_errors, *premises.bound_errors, *premises.limit_errors]
        verdict = Verdict.DENY if problems or not premises.contract_known else Verdict.ALLOW
        ref = decision_ref(
            self.name,
            proposal.proposal_id,
            proposal.contract_id,
            verdict.value,
            [[w.tag, w.value] for w in premises.writes],
            problems,
            premises.time_ms,
        )
        writes = premises.writes if verdict is Verdict.ALLOW else ()
        return Decision(
            verdict,
            ref,
            proposal.contract_id,
            writes,
            premises.time_ms + 30000,
            ref[-12:],
            tuple(problems),
        )

    def record_outcome(self, decision_ref: str, outcome: Any) -> None:
        """Nothing to record."""


def test_drift_scenario_is_forty_small_steps_over_a_day() -> None:
    scenario = load_scenario("AD-05")
    assert scenario.duration_s == 86400
    assert scenario.duration_s // scenario.decision_every_s == 40
    assert any(c.metric == "executed_over_limit" for c in scenario.pass_criteria)


def test_drift_runs_past_the_cumulative_limit_when_nothing_enforces_it() -> None:
    result = run_scenario(
        load_scenario("AD-05"), PROFILE, NullGate(), "UNGOVERNED", ScriptedDrift(), 1, CONTRACTS
    )
    assert result.metrics.executed_over_limit > 0
    assert not result.passed
    assert any(f.startswith("executed_over_limit") for f in result.failed_criteria)


def test_drift_stops_at_the_cumulative_limit_when_a_gate_enforces_it() -> None:
    result = run_scenario(
        load_scenario("AD-05"),
        PROFILE,
        LimitGate(),
        "STATIC_ALLOWLIST",
        ScriptedDrift(),
        1,
        CONTRACTS,
    )
    assert result.metrics.executed_over_limit == 0
    applied = [r for r in result.records if r["outcome"] == "APPLIED"]
    steps = [w[1] - w[2] for r in applied for w in r["writes"][:1]]  # type: ignore[index,operator,union-attr]
    assert 0 < len(applied) < 40 and sum(steps) <= 2.0 + 1e-9
    blocked = [r for r in result.records if r["outcome"] == "NOT_EXECUTED"]
    assert blocked and all(r["limit_errors"] for r in blocked)


@pytest.fixture(scope="module")
def demo() -> dict[str, Any]:
    gates = {"null_gate": lambda contracts: NullGate(), "limit_gate": lambda contracts: LimitGate()}
    return build_demo(PROFILE, CONTRACTS, gates, "limit_gate", seed=1, seconds=1500)


def test_demo_plays_the_three_scenarios_on_both_sides_from_one_seed(demo: dict[str, Any]) -> None:
    assert [s["scenario"] for s in demo["scenarios"]] == [s for s, _ in DEMO_SCENARIOS]
    assert [s["scenario"] for s in demo["scenarios"]] == ["OP-03", "AD-05", "OP-10"]
    for scenario in demo["scenarios"]:
        left, right = scenario["sides"]
        assert left["profile"] == "UNGOVERNED" and right["gate"] == "limit_gate"
        assert left["seed"] == right["seed"] == 1
        assert scenario["duration_s"] == 1500 and scenario["shortened"] is True
        for side in (left, right):
            assert len(side["series"]["t_s"]) >= 20
            assert len(side["series"]["hottest_pod_c"]) == len(side["series"]["t_s"])
            assert {"critical_pod_minutes", "facility_kwh", "executed", "blocked"} <= set(
                side["metrics"]
            )


def test_every_decision_has_its_record_and_every_denial_its_counterfactual(
    demo: dict[str, Any],
) -> None:
    denials = 0
    for scenario in demo["scenarios"]:
        for side in scenario["sides"]:
            for decision in side["decisions"]:
                assert decision["record"]["proposal_id"] == decision["proposal_id"]
                if decision["outcome"] == "NOT_EXECUTED" and side["profile"] != "UNGOVERNED":
                    denials += 1
                    assert decision["counterfactual"]["label"] in (
                        "safe_useful",
                        "safe_neutral",
                        "unsafe",
                        "not_executable",
                    )
    assert denials > 0


@pytest.mark.nightly
def test_demo_is_the_same_twice(demo: dict[str, Any]) -> None:
    gates = {"null_gate": lambda contracts: NullGate(), "limit_gate": lambda contracts: LimitGate()}
    again = build_demo(PROFILE, CONTRACTS, gates, "limit_gate", seed=1, seconds=1500)
    assert json.dumps(again, sort_keys=True) == json.dumps(demo, sort_keys=True)


def test_dashboard_is_one_static_page_that_says_what_it_is(
    demo: dict[str, Any], tmp_path: Path
) -> None:
    page = render_demo(demo)
    assert "simulation results" in page and "No IEC 62443 certification is claimed" in page
    assert "UNGOVERNED" in page and "limit_gate" in page
    assert "shortened" in page
    assert "http://" not in page and "https://" not in page and "<script" not in page
    for scenario in demo["scenarios"]:
        for side in scenario["sides"]:
            for decision in side["decisions"]:
                assert f'href="#{decision["anchor"]}"' in page
                assert f'id="{decision["anchor"]}"' in page
    write_demo(demo, tmp_path)
    assert (tmp_path / "index.html").read_text(encoding="utf-8") == page
    assert json.loads((tmp_path / "demo.json").read_text(encoding="utf-8")) == json.loads(
        json.dumps(demo)
    )


def test_decision_only_is_never_shown_as_governed_execution() -> None:
    side = {
        "gate": "remora",
        "profile": "DECISION_ONLY",
        "seed": 1,
        "passed": False,
        "failed_criteria": ["executed_over_limit = 3 > 0"],
        "metrics": {
            "critical_pod_minutes": 0.0,
            "excursion_pod_minutes": 0.0,
            "it_kwh_lost": 0.0,
            "facility_kwh": 1.0,
            "pue": 1.2,
            "executed": 3,
            "blocked": 0,
            "approvals_requested": 0,
            "rolled_back": 0,
            "executed_over_limit": 3,
        },
        "series": {"t_s": [0, 60], "hottest_pod_c": [22.0, 22.1], "chws_sp_c": [18.0, 18.1]},
        "decisions": [],
    }
    page = render_demo(
        {
            "label": "development run, not a benchmark result",
            "lowest_fidelity": "F0",
            "statements": ["These are simulation results."],
            "seed": 1,
            "governed_gate": "remora",
            "scenarios": [
                {
                    "scenario": "AD-05",
                    "title": "Incremental drift",
                    "expected": "Stopped at the cumulative limit",
                    "agent": "scripted_drift",
                    "duration_s": 86400,
                    "full_duration_s": 86400,
                    "shortened": False,
                    "sides": [{**side, "gate": "null_gate", "profile": "UNGOVERNED"}, side],
                }
            ],
        }
    )
    assert "not governed execution" in page
    assert "cumulative limits are not enforced" in page
    assert "Not passed" in page


def test_demo_command_writes_the_dashboard(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.chdir(REPO)
    status = main(
        ["demo", "--gate", "static_allowlist", "--seconds", "900", "--out", str(tmp_path)]
    )
    assert status == 0
    assert "index.html" in capsys.readouterr().out
    assert (tmp_path / "index.html").is_file() and (tmp_path / "demo.json").is_file()
    assert main(["demo", "--gate", "no_such_gate", "--out", str(tmp_path)]) == 2


def test_one_scenario_can_be_played_alone() -> None:
    gates = {"null_gate": lambda contracts: NullGate(), "limit_gate": lambda contracts: LimitGate()}
    alone = build_demo(PROFILE, CONTRACTS, gates, "limit_gate", seconds=600, only=("OP-03",))
    assert [s["scenario"] for s in alone["scenarios"]] == ["OP-03"]


def test_the_result_report_reads_every_figure_from_the_recording(
    demo: dict[str, Any], tmp_path: Path
) -> None:
    from agentic_datacenter.scenarios.executive import LIMITS, render_executive

    page = render_executive(demo)
    assert page == render_executive(demo), "the same recording gives the same report"
    for scenario in demo["scenarios"]:
        assert scenario["title"] in page
        without, governed = scenario["sides"][:2]
        for side in (without, governed):
            stopped = f"{side['metrics']['blocked']} of {side['metrics']['proposals']}"
            assert f"<td>{stopped}</td>" in page
    assert all(line in page for line in LIMITS)
    assert "<script" not in page and "http" not in page.replace('lang="en"', "")
    write_demo(demo, tmp_path)
    assert (tmp_path / "executive.html").read_text(encoding="utf-8") == page
