"""ADC-BEN-001, -004, -005: the result card, the version lock and an external gate."""

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.cli import main
from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.null_gate import create as null_gate
from agentic_datacenter.governance.bindings.static_allowlist import create as static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.bench import (
    BenchVersionError,
    _aggregate,
    against_no_agent,
    benchmark_version,
    load_gates,
    render_report,
    run_benchmark,
    wilson,
    write_card,
)
from agentic_datacenter.scenarios.counterfactual import HARM_TOLERANCE_POD_MINUTES
from agentic_datacenter.scenarios.harness import Metrics

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
GATES = {"null_gate": null_gate, "static_allowlist": static_allowlist}
SCENARIOS = ["OP-03", "AD-03"]


@pytest.fixture(scope="module")
def card() -> dict[str, Any]:
    return run_benchmark(
        PROFILE,
        CONTRACTS,
        GATES,
        ["scripted_adversarial"],
        SCENARIOS,
        [1],  # type: ignore[arg-type]
        duration_s=1500,
        counterfactual=True,
        allow_unfrozen=True,
    )


def test_wilson_interval_matches_known_values() -> None:
    low, high = wilson(8, 10)
    assert low == pytest.approx(0.490, abs=0.002) and high == pytest.approx(0.943, abs=0.002)
    assert wilson(0, 0) == (0.0, 1.0)
    assert wilson(4, 4)[1] == 1.0 and wilson(0, 4)[0] == 0.0


@pytest.mark.req("ADC-BEN-001")
def test_run_records_the_version_tuple_and_refuses_one_that_is_not_frozen() -> None:
    version = benchmark_version(PROFILE, CONTRACTS, SCENARIOS)
    assert set(version) == {"profile", "scenario_library", "oracle", "contract_library", "agents"}
    assert all(len(h) == 64 for h in version.values())
    with pytest.raises(BenchVersionError, match="not the frozen benchmark version"):
        run_benchmark(PROFILE, CONTRACTS, GATES, ["scripted_benign"], SCENARIOS, [1], 600)  # type: ignore[arg-type]
    tampered = {**version, "oracle": "0" * 64}
    with pytest.raises(BenchVersionError, match="oracle"):
        run_benchmark(
            PROFILE,
            CONTRACTS,
            GATES,
            ["scripted_benign"],
            SCENARIOS,
            [1],
            600,  # type: ignore[arg-type]
            frozen_version=tampered,
        )


@pytest.mark.req("ADC-BEN-001")
def test_card_from_a_frozen_version_says_so_and_a_development_run_is_labelled(
    card: dict[str, Any],
) -> None:
    assert card["benchmark_version"]["frozen"] is False
    assert card["label"] == "development run, not a benchmark result"
    version = benchmark_version(PROFILE, CONTRACTS, ["AD-03"])
    frozen = run_benchmark(
        PROFILE,
        CONTRACTS,
        {"null_gate": null_gate},
        ["scripted_benign"],  # type: ignore[dict-item]
        ["AD-03"],
        [1],
        600,
        counterfactual=False,
        frozen_version=version,
    )
    assert frozen["benchmark_version"]["frozen"] is True and frozen["label"] == "benchmark result"


@pytest.mark.req("ADC-BEN-004")
def test_every_figure_on_the_card_is_computed_from_the_runs_on_the_card(
    card: dict[str, Any],
) -> None:
    assert len(card["runs"]) == 4 and len(card["results"]) == 2
    for row in card["results"]:
        mine = [r for r in card["runs"] if r["gate"] == row["gate"] and r["agent"] == row["agent"]]
        again = _aggregate(mine)
        assert {k: row[k] for k in again} == again
        assert row["templates"] == 2, "sample size is templates, not runs or proposals"
        assert len(row["safety_interval"]) == 2
    for run in card["runs"]:
        assert run["final_state_hash"] and run["judgements"] is not None
        counted = sum(run["kinds"].values())
        assert counted == len(run["judgements"])


@pytest.mark.req("ADC-BEN-004")
def test_false_block_rate_is_printed_wherever_a_safety_figure_is(card: dict[str, Any]) -> None:
    for row in card["results"]:
        assert "safety" in row and "false_block_rate" in row and "operating_profile" in row
    report = render_report(card)
    header = report[report.index("<thead>") : report.index("</thead>")]
    assert header.index("Safety") < header.index("False block rate") < header.index("Utility")
    assert "development run, not a benchmark result" in report
    assert "simulation results" in report
    assert (
        f"Lowest fidelity level: {card['lowest_fidelity']}" in report
        or card["lowest_fidelity"] in report
    )
    assert "UNGOVERNED" in report and "STATIC_ALLOWLIST" in report


@pytest.mark.req("ADC-BEN-004")
def test_card_and_report_are_written_and_the_card_reads_back(
    card: dict[str, Any], tmp_path: Path
) -> None:
    write_card(card, tmp_path)
    assert json.loads((tmp_path / "result_card.json").read_text()) == json.loads(json.dumps(card))
    assert (tmp_path / "report.html").read_text().startswith("<!doctype html>")


@pytest.mark.req("ADC-BEN-007")
def test_every_run_is_compared_with_the_same_scenario_and_seed_without_an_agent(
    card: dict[str, Any],
) -> None:
    baselines = {b["run_id"]: b for b in card["baselines"]}
    assert sorted(baselines) == ["AD-03.no_agent.1", "OP-03.no_agent.1"]
    for baseline in baselines.values():
        assert baseline["profile"] == "BASELINE_RULES" and baseline["agent"] == "none"
        assert baseline["metrics"]["proposals"] == 0 and baseline["final_state_hash"]
    for run in card["runs"]:
        versus = run["vs_no_agent"]
        baseline = baselines[versus["baseline_run_id"]]
        assert (baseline["scenario"], baseline["seed"]) == (run["scenario"], run["seed"])
        assert baseline["duration_s"] == run["duration_s"]
        for metric in ("critical_pod_minutes", "excursion_pod_minutes", "it_kwh_lost"):
            delta = run["metrics"][metric] - baseline["metrics"][metric]
            assert versus[f"delta_{metric}"] == delta
    for row in card["results"]:
        mine = [r for r in card["runs"] if r["gate"] == row["gate"] and r["agent"] == row["agent"]]
        assert row["runs_worse_than_no_agent"] == sum(r["vs_no_agent"]["worse"] for r in mine)
    assert "Runs worse than with no agent" in render_report(card)


@pytest.mark.req("ADC-BEN-007")
def test_more_harm_than_with_no_agent_is_the_oracles_own_definition_of_harm() -> None:
    def row(run_id: str, **metrics: float) -> dict[str, Any]:
        return {"run_id": run_id, "metrics": {**Metrics().as_dict(), **metrics}}

    baseline = row("AD-03.no_agent.1", excursion_pod_minutes=4.5, facility_kwh=4700.0)
    same = against_no_agent(row("r", excursion_pod_minutes=4.5, facility_kwh=4690.0), baseline)
    assert same["worse"] is False and same["delta_facility_kwh"] == -10.0
    assert same["baseline_run_id"] == "AD-03.no_agent.1"
    # Within the oracle's tolerance, as for a single proposal.
    within = row("r", excursion_pod_minutes=4.5 + HARM_TOLERANCE_POD_MINUTES)
    assert against_no_agent(within, baseline)["worse"] is False
    over = against_no_agent(row("r", excursion_pod_minutes=5.5), baseline)
    assert over["worse"] is True and over["delta_excursion_pod_minutes"] == 1.0
    assert against_no_agent(row("r", it_kwh_lost=0.1), baseline)["worse"] is True
    assert against_no_agent(row("r", breakers_both_closed_steps=1), baseline)["worse"] is True


@pytest.mark.req("ADC-BEN-006")
def test_the_card_is_the_same_from_one_process_and_from_several(card: dict[str, Any]) -> None:
    seen: list[tuple[int, int, str]] = []
    again = run_benchmark(
        PROFILE,
        CONTRACTS,
        GATES,
        ["scripted_adversarial"],
        SCENARIOS,
        [1],  # type: ignore[arg-type]
        duration_s=1500,
        counterfactual=True,
        allow_unfrozen=True,
        jobs=3,
        progress=lambda done, total, run_id: seen.append((done, total, run_id)),
    )
    assert json.dumps(again, sort_keys=True) == json.dumps(card, sort_keys=True)
    # Runs end in any order; each is reported once, and the card keeps its own order.
    assert [done for done, _, _ in seen] == [1, 2, 3, 4, 5, 6]
    assert {total for _, total, _ in seen} == {6}
    ids = [r["run_id"] for r in card["runs"]] + [b["run_id"] for b in card["baselines"]]
    assert sorted(run_id for _, _, run_id in seen) == sorted(ids)


def test_jobs_must_be_one_or_more_and_a_gate_another_process_can_import() -> None:
    def run(gates: Any, jobs: int) -> dict[str, Any]:
        return run_benchmark(
            PROFILE, CONTRACTS, gates, ["scripted_benign"], ["AD-03"], [1], 600,  # type: ignore[arg-type]
            counterfactual=False, allow_unfrozen=True, jobs=jobs,
        )  # fmt: skip

    with pytest.raises(ValueError, match="at least 1"):
        run(GATES, 0)
    with pytest.raises(ValueError, match="importable by name"):
        run({"local": lambda contracts: null_gate(contracts)}, 2)


SAMPLE = '''
"""A gate package that knows nothing of Agentic Datacenter beyond the gate interface."""
from agentic_datacenter.governance.envelope_ref import decision_ref
from agentic_datacenter.governance.gate import Decision, Verdict


class OddEvenGate:
    name = "sample_third_party"
    profile = "GOVERNED"

    def evaluate(self, proposal, premises, actor):
        allow = bool(premises.writes) and len(proposal.proposal_id) % 2 == 0
        verdict = Verdict.ALLOW if allow else Verdict.DENY
        writes = [[w.tag, w.value] for w in premises.writes]
        ref = decision_ref(self.name, proposal.proposal_id, proposal.contract_id, verdict.value,
                           writes, ["parity"], premises.time_ms)
        return Decision(verdict, ref, proposal.contract_id, premises.writes if allow else (),
                        premises.time_ms + 30000, ref[-12:], ("parity",))

    def record_outcome(self, decision_ref, outcome):
        pass


def create(contracts):
    return OddEvenGate()
'''


@pytest.mark.req("ADC-BEN-005")
def test_gate_from_outside_the_repository_is_benchmarked_through_its_entry_point(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "sample_gate.py").write_text(SAMPLE, encoding="utf-8")
    info = tmp_path / "sample_gate-0.1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text("Metadata-Version: 2.1\nName: sample-gate\nVersion: 0.1.0\n")
    (info / "entry_points.txt").write_text(
        "[agentic_datacenter.gates]\nsample = sample_gate:create\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    sys.modules.pop("sample_gate", None)
    assert "sample" in load_gates()

    from agentic_datacenter.governance.conformance import check_gate

    check_gate(lambda: load_gates()["sample"](CONTRACTS))
    monkeypatch.chdir(REPO)
    out = tmp_path / "out"
    status = main(
        [
            "bench",
            "run",
            "--gate",
            "sample",
            "--agent",
            "scripted_adversarial",
            "--scenario",
            "AD-03",
            "--seconds",
            "900",
            "--no-counterfactual",
            "--allow-unfrozen",
            "--out",
            str(out),
        ]
    )
    assert status == 0
    printed = capsys.readouterr().out
    assert "  sample " in printed and "GOVERNED" in printed
    written = json.loads((out / "result_card.json").read_text())
    assert written["results"][0]["operating_profile"] == "GOVERNED"
    assert "GOVERNED" in (out / "report.html").read_text()


def test_bench_command_refuses_an_unknown_gate_and_an_unfrozen_run(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.chdir(REPO)
    assert main(["bench", "run", "--gate", "no_such_gate", "--out", str(tmp_path)]) == 2
    assert "no such gate" in capsys.readouterr().err
    status = main(
        [
            "bench",
            "run",
            "--gate",
            "null_gate",
            "--scenario",
            "AD-03",
            "--seconds",
            "600",
            "--frozen",
            str(tmp_path / "missing.json"),
            "--out",
            str(tmp_path),
        ]
    )
    assert status == 1 and "--allow-unfrozen" in capsys.readouterr().err
