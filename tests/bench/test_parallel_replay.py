"""ADR 0026: the replay of one run spread over processes judges as the replay in one."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
import yaml
from agentic_datacenter.scenarios.parallel_replay import (
    ReplayMismatch,
    helpers_for,
    judge_run_parallel,
    shares,
)

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.null_gate import create as null_gate
from agentic_datacenter.governance.bindings.static_allowlist import create as static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios import bench as bench_module
from agentic_datacenter.scenarios import parallel_replay
from agentic_datacenter.scenarios.agents import ScriptedAdversarial
from agentic_datacenter.scenarios.bench import benchmark_version, run_benchmark
from agentic_datacenter.scenarios.cli import bench
from agentic_datacenter.scenarios.counterfactual import judge_run
from agentic_datacenter.scenarios.scenario import library_ids, load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
LENGTH = 1800


def _keeps_state(contracts: ContractLibrary) -> Any:
    """The allowlist, as a gate whose state a capture cannot hold but a snapshot can."""
    gate: Any = static_allowlist(contracts)
    gate.restorable = False
    gate.snapshot_state = lambda: {"outcomes": dict(gate.outcomes)}
    gate.restore_state = lambda state: setattr(gate, "outcomes", dict(state["outcomes"]))
    return gate


def _cannot_be_restored(contracts: ContractLibrary) -> Any:
    """The allowlist, as a gate that every branch must be played from the start for."""
    gate: Any = static_allowlist(contracts)
    gate.restorable = False
    return gate


def _arguments(make_gate: Any) -> tuple[Any, ...]:
    return (
        load_scenario("AD-03"), PROFILE, make_gate, "STATIC_ALLOWLIST",
        ScriptedAdversarial, 1, CONTRACTS, LENGTH,
    )  # fmt: skip


def _same(one: tuple[Any, Any], other: tuple[Any, Any]) -> None:
    (result, judged), (expected, expected_judged) = one, other
    assert judged == expected_judged
    assert result.judging == expected.judging
    assert result.metrics == expected.metrics
    assert result.records == expected.records
    assert result.state_hashes == expected.state_hashes
    assert (result.passed, result.failed_criteria) == (expected.passed, expected.failed_criteria)


@pytest.mark.parametrize(
    ("make_gate", "horizon_s", "max_judged", "branches_from"),
    [
        (static_allowlist, None, None, "capture"),
        (static_allowlist, 300, None, "capture"),
        (static_allowlist, 300, 3, "capture"),
        (_keeps_state, 300, None, "gate snapshot"),
        (_keeps_state, None, 3, "gate snapshot"),
        (_cannot_be_restored, 300, 3, "start of run"),
    ],
)
def test_shares_judged_apart_give_the_judgements_of_the_replay_in_one(
    make_gate: Any, horizon_s: int | None, max_judged: int | None, branches_from: str
) -> None:
    expected = judge_run(*_arguments(make_gate), horizon_s=horizon_s, max_judged=max_judged)
    assert expected[1] and expected[0].judging["branches_from"] == branches_from
    made = judge_run_parallel(
        *_arguments(make_gate), horizon_s=horizon_s, max_judged=max_judged,
        replay_jobs=2, min_work_runs=0, spawn=False,
    )  # fmt: skip
    _same(made, expected)


def test_processes_of_their_own_give_the_same_judgements() -> None:
    expected = judge_run(*_arguments(static_allowlist), horizon_s=None)
    made = judge_run_parallel(
        *_arguments(static_allowlist), horizon_s=None, replay_jobs=2, min_work_runs=0
    )
    _same(made, expected)


def test_one_replay_job_is_the_replay_in_one_and_nothing_else(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, Any]] = []

    def counted(*args: Any, **kwargs: Any) -> Any:
        calls.append(kwargs)
        return judge_run(*args, **kwargs)

    monkeypatch.setattr(parallel_replay, "judge_run", counted)
    made = judge_run_parallel(*_arguments(static_allowlist), horizon_s=300, replay_jobs=1)
    assert calls == [{"horizon_s": 300, "max_judged": None}]
    _same(made, judge_run(*_arguments(static_allowlist), horizon_s=300))


def test_a_replay_too_small_to_share_is_made_in_one(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each helper repeats the run, so a small replay is slower shared than whole."""
    shared: list[int] = []
    monkeypatch.setattr(parallel_replay, "_judge_shares", lambda *a, **k: shared.append(1) or [])
    made = judge_run_parallel(*_arguments(static_allowlist), horizon_s=300, replay_jobs=4)
    assert shared == []
    _same(made, judge_run(*_arguments(static_allowlist), horizon_s=300))


def test_the_number_of_helpers_follows_the_work() -> None:
    week = 604_800
    # A full replay of the week-long scenario: every helper asked for has work.
    assert helpers_for(work_s=335 * week, length_s=week, judged=671, replay_jobs=15) == 15
    # The season's bounds on it, 16 branches of a day: not worth sharing.
    assert helpers_for(work_s=16 * 86_400, length_s=week, judged=16, replay_jobs=15) == 1
    # A short scenario, 64 branches of an hour on four hours: four helpers.
    assert helpers_for(work_s=64 * 3600, length_s=4 * 3600, judged=64, replay_jobs=15) == 4
    assert helpers_for(work_s=10**9, length_s=3600, judged=3, replay_jobs=15) == 3
    assert helpers_for(work_s=10**9, length_s=3600, judged=64, replay_jobs=1) == 1
    assert helpers_for(work_s=0, length_s=3600, judged=0, replay_jobs=8) == 1


def test_every_branch_is_in_one_share_and_the_shares_are_even() -> None:
    costs = {f"p{i}": 1000 - 7 * i for i in range(100)}
    made = shares(list(costs), costs.__getitem__, 4)
    assert len(made) == 4
    assert sorted(item for share in made for item in share) == sorted(costs)
    totals = [sum(costs[item] for item in share) for share in made]
    assert max(totals) - min(totals) <= max(costs.values())
    assert made == shares(list(costs), costs.__getitem__, 4), "the same on every machine"


def test_a_helper_whose_run_differs_stops_the_benchmark(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same seed gives the same run. If it does not, no judgement is to be trusted."""
    real = parallel_replay._judge_share

    def another_run(*args: Any, **kwargs: Any) -> Any:
        final_hash, judged = real(*args, **kwargs)
        return "0" * 64, judged

    monkeypatch.setattr(parallel_replay, "_judge_share", another_run)
    with pytest.raises(ReplayMismatch, match="state hash"):
        judge_run_parallel(
            *_arguments(static_allowlist), horizon_s=300,
            replay_jobs=2, min_work_runs=0, spawn=False,
        )  # fmt: skip


@pytest.mark.req("ADC-BEN-006")
def test_the_card_is_the_same_whatever_the_number_of_replay_jobs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def card(replay_jobs: int) -> str:
        made = run_benchmark(
            PROFILE, CONTRACTS, {"null_gate": null_gate, "static_allowlist": static_allowlist},
            ["scripted_adversarial"], ["AD-03"], [1], LENGTH,
            allow_unfrozen=True, replay_jobs=replay_jobs,
        )  # fmt: skip
        return json.dumps(made, indent=2, sort_keys=True)

    whole = card(1)
    used: list[int] = []
    real = parallel_replay._judge_shares
    monkeypatch.setattr(parallel_replay, "MIN_WORK_RUNS", 0)
    monkeypatch.setattr(
        parallel_replay, "_judge_shares", lambda *a, **k: used.append(1) or real(*a, **k)
    )
    assert card(2) == whole
    assert used, "the replay was shared"


def test_the_benchmark_refuses_fewer_than_one_replay_job() -> None:
    with pytest.raises(ValueError, match="replay_jobs"):
        run_benchmark(
            PROFILE, CONTRACTS, {"null_gate": null_gate}, ["scripted_adversarial"], ["AD-03"],
            [1], LENGTH, allow_unfrozen=True, replay_jobs=0,
        )  # fmt: skip


def test_the_command_takes_the_number_of_replay_jobs(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    seen: dict[str, Any] = {}

    def stop(*args: Any, **kwargs: Any) -> Any:
        seen.update(kwargs)
        raise bench_module.BenchVersionError("stopped by the test")

    monkeypatch.setattr("agentic_datacenter.scenarios.cli.run_benchmark", stop)
    common = ["run", "--gate", "null_gate", "--allow-unfrozen", "--out", str(tmp_path)]
    assert bench([*common, "--replay-jobs", "5"]) == 1
    assert seen["replay_jobs"] == 5
    assert bench(common) == 1
    assert seen["replay_jobs"] == 1
    assert bench([*common, "--replay-jobs", "0"]) == 2
    assert "--replay-jobs must be at least 1" in capsys.readouterr().err


def test_the_runner_workflow_passes_the_number_of_replay_jobs() -> None:
    data = yaml.safe_load((REPO / ".github/workflows/bench-runner.yml").read_text("utf-8"))
    assert "replay_jobs" in data[True]["workflow_dispatch"]["inputs"]
    run = "\n".join(step.get("run", "") for step in data["jobs"]["bench"]["steps"])
    assert "--replay-jobs" in run and "inputs.replay_jobs" in run


def test_the_frozen_benchmark_version_is_the_version_of_this_code() -> None:
    """The parallel replay is beside the oracle, not in it: the frozen hashes still hold."""
    frozen = json.loads((REPO / "docs/bench/VERSION.json").read_text(encoding="utf-8"))
    assert benchmark_version(PROFILE, CONTRACTS, library_ids()) == frozen["version"]
