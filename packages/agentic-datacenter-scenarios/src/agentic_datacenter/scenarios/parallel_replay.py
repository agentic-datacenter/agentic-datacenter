"""The counterfactual replay of one run, spread over processes (ADR 0026).

The replay of a run is one branch per proposal, and no branch depends on
another. :func:`agentic_datacenter.scenarios.counterfactual.judge_run` plays them one
after another in one process, which for a week-long scenario replayed to its
end takes days. Here the branches are dealt out to helper processes.

The oracle is not changed, and its source is part of the frozen benchmark
version. It still decides which proposals are judged, and it still holds the
rule that labels a branch. A helper repeats the run from the same seed, which
gives the same run, and plays its share of the branches as the oracle would.
The judgements are the same; a test compares them for every kind of gate.
"""

from __future__ import annotations

import multiprocessing
import pickle
import sys
from collections.abc import Callable, Sequence
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import replace
from typing import Any

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.governance.gate import GovernanceGate
from agentic_datacenter.scenarios.agents import Agent
from agentic_datacenter.scenarios.counterfactual import Judgement, judge_run, label
from agentic_datacenter.scenarios.harness import HASH_EVERY_S, RunResult, ScenarioRun
from agentic_datacenter.scenarios.scenario import Scenario

#: Simulated run lengths of replay each helper must have to be worth starting.
#: A helper repeats the run before it plays a branch, twice for a gate restored
#: from snapshots, so below this the replay is faster in one process.
MIN_WORK_RUNS = 4

#: A proposal to judge, as the oracle chose it, and the second of its decision.
Item = tuple[Judgement, int]


class ReplayMismatch(RuntimeError):
    """A helper's run was not the run of the process that asked it."""


def helpers_for(
    work_s: int, length_s: int, judged: int, replay_jobs: int, min_work_runs: int = MIN_WORK_RUNS
) -> int:
    """Return how many helpers a replay of *work_s* simulated seconds is worth.

    At most *replay_jobs*, at most one per branch, and none that would have
    less than *min_work_runs* run lengths of replay to do.
    """
    if replay_jobs <= 1 or judged < 2:
        return 1
    by_work = replay_jobs if min_work_runs <= 0 else work_s // (min_work_runs * length_s)
    return int(max(1, min(replay_jobs, judged, by_work)))


def shares[T](items: Sequence[T], cost: Callable[[T], int], helpers: int) -> list[list[T]]:
    """Deal *items* into *helpers* shares of about the same cost.

    The most costly item goes first, each to the share with the least so far,
    so the shares differ by at most one item. The same items give the same
    shares on every machine. Which share a branch is in changes nothing in its
    judgement.
    """
    out: list[list[int]] = [[] for _ in range(helpers)]
    totals = [0] * helpers
    for index in sorted(range(len(items)), key=lambda i: (-cost(items[i]), i)):
        least = totals.index(min(totals))
        out[least].append(index)
        totals[least] += cost(items[index])
    return [[items[i] for i in sorted(share)] for share in out]


def _end(second: int, horizon_s: int | None, length: int) -> int:
    """Return the second a branch from *second* is played to, as the oracle counts it."""
    if horizon_s is None:
        return length
    return min(length, -(-(second + horizon_s) // HASH_EVERY_S) * HASH_EVERY_S)


def _judge_share(
    scenario: Scenario,
    profile: Profile,
    make_gate: Callable[[ContractLibrary], GovernanceGate],
    operating_profile: str,
    make_agent: Callable[[], Agent],
    seed: int,
    contracts: ContractLibrary,
    duration_s: int | None,
    horizon_s: int | None,
    share: Sequence[Item],
) -> tuple[str, list[Judgement]]:
    """Repeat the run and judge the proposals of *share*; what one helper does.

    The steps are those of ``judge_run`` for the branches it is given: the
    same captures and gate snapshots, the same forced outcome, the same end,
    and the oracle's own :func:`label`.

    Returns:
        The final state hash of the repeated run, for the caller to compare
        with its own, and the judgements in the order of *share*.
    """

    def new_run() -> ScenarioRun:
        return ScenarioRun(
            scenario, profile, make_gate, operating_profile, make_agent, seed, contracts,
            duration_s,
        )  # fmt: skip

    wanted = {second for _, second in share}
    actual_run = new_run()
    restorable = getattr(actual_run.gate, "restorable", True)
    snapshots = not restorable and hasattr(actual_run.gate, "snapshot_state")
    actual_run.capture_at = wanted if restorable else ()
    actual = actual_run.run(keep_captures=True)
    source = actual_run
    if snapshots:
        source = new_run()
        source.capture_at = source.snapshot_gate_at = wanted
        source.advance(source.length, keep_captures=True)
    judgements = []
    for index, (chosen, second) in enumerate(share):
        branch = new_run()
        if restorable or snapshots:
            branch.restore(source.captures[second])
        if snapshots:
            branch.gate.restore_state(source.gate_snapshots[second])  # type: ignore[attr-defined]
        if all(later != second for _, later in share[index + 1 :]):
            source.captures.pop(second, None)
            source.gate_snapshots.pop(second, None)
        branch.world.path.forced[chosen.proposal_id] = "block" if chosen.executed else "execute"
        end = _end(second, horizon_s, actual_run.length)
        if end < actual_run.length:
            branch.advance(end)
            other_m, actual_m = branch.measured(), actual_run.marks[end]
            other_records = branch.world.path.records()
        else:
            other = branch.run()
            other_m, actual_m, other_records = other.metrics, actual.metrics, other.records
        other_record = next(r for r in other_records if r["proposal_id"] == chosen.proposal_id)
        if not chosen.executed and other_record["outcome"] not in ("APPLIED", "ROLLED_BACK"):
            verdict = "not_executable"
            executed_m = blocked_m = actual_m
        else:
            executed_m, blocked_m = (actual_m, other_m) if chosen.executed else (other_m, actual_m)
            verdict = label(executed_m, blocked_m)
        e, b = executed_m, blocked_m
        judgements.append(
            replace(
                chosen,
                label=verdict,
                delta_critical_pod_minutes=e.critical_pod_minutes - b.critical_pod_minutes,
                delta_excursion_pod_minutes=e.excursion_pod_minutes - b.excursion_pod_minutes,
                delta_it_kwh_lost=e.it_kwh_lost - b.it_kwh_lost,
                delta_facility_kwh=e.facility_kwh - b.facility_kwh,
            )
        )
    return (actual.state_hashes[-1][1] if actual.state_hashes else ""), judgements


def _judge_shares(
    arguments: tuple[Any, ...], parts: Sequence[Sequence[Item]], spawn: bool, name: str
) -> list[tuple[str, list[Judgement]]]:
    """Judge every share, each in a process of its own unless *spawn* is false."""
    calls: list[tuple[Any, ...]] = [(*arguments, part) for part in parts]
    if not spawn:
        return [_judge_share(*call) for call in calls]
    context = multiprocessing.get_context("spawn")
    out: list[tuple[str, list[Judgement]] | None] = [None] * len(parts)
    with ProcessPoolExecutor(len(parts), mp_context=context, max_tasks_per_child=1) as pool:
        pending = {pool.submit(_judge_share, *call): i for i, call in enumerate(calls)}
        for done, future in enumerate(as_completed(pending), start=1):
            out[pending[future]] = future.result()
            print(f"  replay of {name}: part {done} of {len(parts)} done", file=sys.stderr)
            sys.stderr.flush()
    return [part for part in out if part is not None]


def judge_run_parallel(
    scenario: Scenario,
    profile: Profile,
    make_gate: Callable[[ContractLibrary], GovernanceGate],
    operating_profile: str,
    make_agent: Callable[[], Agent],
    seed: int,
    contracts: ContractLibrary,
    duration_s: int | None = None,
    *,
    horizon_s: int | None = None,
    max_judged: int | None = None,
    replay_jobs: int = 1,
    min_work_runs: int = MIN_WORK_RUNS,
    spawn: bool = True,
) -> tuple[RunResult, list[Judgement]]:
    """Run a scenario and judge its proposals as ``judge_run`` does, in *replay_jobs* processes.

    With one replay job, or a replay too small to be worth sharing
    (:func:`helpers_for`), this is ``judge_run`` and nothing else. Otherwise
    the oracle is asked which proposals it judges, with a replay of one minute
    each; the branches are dealt out (:func:`shares`); every helper repeats the
    run and plays its share to the real horizon; and the judgements are put
    back in the oracle's order. The result is what ``judge_run`` returns.

    Raises:
        ReplayMismatch: If a helper's run ended in another state than this
            process's run, or a judgement is missing.
        ValueError: If helpers are to be started and the gate or the agent
            cannot be imported by name in another process.
    """
    run = (scenario, profile, make_gate, operating_profile, make_agent, seed, contracts, duration_s)

    def in_one() -> tuple[RunResult, list[Judgement]]:
        return judge_run(*run, horizon_s=horizon_s, max_judged=max_judged)

    length = min(duration_s or scenario.duration_s, scenario.duration_s)
    if replay_jobs <= 1:
        return in_one()
    if max_judged is not None:
        most = max_judged * (_end(0, horizon_s, length) + HASH_EVERY_S)
        if helpers_for(most, length, max_judged, replay_jobs, min_work_runs) == 1:
            return in_one()
    if spawn:
        try:
            pickle.dumps(run)
        except (pickle.PicklingError, AttributeError, TypeError) as exc:
            raise ValueError(
                "with more than one replay job the gate and the agent must be importable "
                f"by name, as an entry point is: {exc}"
            ) from exc
    # The oracle chooses what is judged, and reads from each record what does
    # not depend on the replay. One minute is the shortest branch it plays.
    actual, chosen = judge_run(*run, horizon_s=HASH_EVERY_S, max_judged=max_judged)
    items = [(j, j.time_ms // 1000 - scenario.warmup_s) for j in chosen]

    def cost(item: Item) -> int:
        return _end(item[1], horizon_s, length) - item[1]

    helpers = helpers_for(sum(map(cost, items)), length, len(items), replay_jobs, min_work_runs)
    if helpers == 1:
        return in_one()
    name = f"{scenario.id}, seed {seed}, {actual.gate}, {actual.agent}"
    made = _judge_shares((*run, horizon_s), shares(items, cost, helpers), spawn, name)
    final = actual.state_hashes[-1][1] if actual.state_hashes else ""
    by_proposal: dict[str, Judgement] = {}
    for helper_final, judged in made:
        if helper_final != final:
            raise ReplayMismatch(
                f"a helper's run of {name} ended in state hash {helper_final}, not {final}: "
                "the same seed did not give the same run"
            )
        by_proposal.update((j.proposal_id, j) for j in judged)
    if set(by_proposal) != {j.proposal_id for j in chosen}:
        raise ReplayMismatch(f"the helpers did not judge every proposal of {name}")
    actual.judging["horizon_s"] = horizon_s
    return actual, [by_proposal[j.proposal_id] for j in chosen]
