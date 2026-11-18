# ADR 0026: The replay of one run is spread over processes, beside the oracle

- **Status:** Proposed. Accepted when the PR that adds it is merged by the owner.
- **Date:** 2026-11-18
- **SDD:** 12.1; requirements `ADC-BEN-003`, `ADC-BEN-006`, `ADC-BEN-008`; ADR 0021, 0023

## Context

`--tier full` replays every proposal of a run to the end of its scenario. It is the reference the bounds of the other tiers are checked against, and the rules of the public test have the maintainers run seed 1 of every season with it.

Nearly all of its cost is one scenario. `OP-10` lasts a simulated week, and its hostile agent proposes about 670 times. Each proposal is replayed for half a week on average, so one run costs about 330 simulated weeks.

That work is done in one process. `--jobs` makes several runs at a time, but one run is one process, so more cores do not shorten the longest run. A `full` run of one gate, started on 2026-11-17 on a machine with 16 threads, had not finished after ten hours when this was written.

The branches of a replay do not depend on each other. Each starts from the state before one decision and is compared with the run as it was.

Season 1 is open, and its benchmark version is frozen. The version holds the hash of the oracle's source, `counterfactual.py` and `harness.py`. A change to either file is another benchmark version, and a season cannot change version.

## Decision

1. **A module beside the oracle.** `agentic_datacenter.scenarios.parallel_replay` spreads the replay of one run over helper processes. Neither frozen file is changed, and a test checks that the benchmark version of the code is still the frozen one.
2. **The oracle still chooses and still labels.**
   - `judge_run` is asked which proposals it judges, with a replay of one minute each. That gives the same candidates and the same sample as any other horizon, and what does not depend on the replay: whether the step was executed, whether the contract forbade it, whether a person declined it.
   - The branches are dealt out to the helpers by what each costs, so the helpers finish at about the same time.
   - Each helper repeats the run from the same seed, once, or twice for a gate restored from its own snapshots, as `judge_run` does. It plays its share with the steps of `judge_run`: the same captures and gate snapshots, the same forced outcome, the same end. It labels each branch with the oracle's own `label`.
   - The judgements are put back in the oracle's order.
3. **A helper that made another run stops the benchmark.** Each helper returns the final state hash of the run it repeated. If it is not that of the asking process, no judgement is trusted and no card is written.
4. **Only on request, and only where it pays.** `--replay-jobs <n>` is 1 unless given, and with 1 the oracle does everything, as before. Sharing has two costs: a helper repeats the run before it plays a branch, and asking the oracle what it judges builds a plant for every branch once more. So a replay is shared only when every helper gets at least four run lengths of replay to do, and the branches last six simulated hours or more on average. The bounded tiers are not shared, nor is `full` on a scenario of a few hours. `full` on `OP-10` is.
5. **`--jobs` and `--replay-jobs` multiply.** `--jobs` runs at a time, each with up to `--replay-jobs` helpers. Together they should not exceed the cores. The runner workflow divides the cores between them when `jobs` is left empty.
6. **The card is the same**, byte for byte, whatever the number of replay jobs (`ADC-BEN-006`). The number is not on the card, as the number of jobs is not.

## What is written twice, and how it is kept right

The steps of one branch (restore, force the other outcome, play, compare) are written again in `_judge_share`, about forty lines. They are outside the frozen hash.

- `tests/bench/test_parallel_replay.py` compares what the helpers make with what `judge_run` makes, judgement for judgement and record for record, for a gate judged from captures, a gate restored from its own snapshots, and a gate played from the start; to the end of the run, to a horizon, and with a sample.
- The same file makes one card with one replay job and one with two, and compares the text.
- Anyone who doubts a card made with replay jobs can make it again with `--replay-jobs 1` and compare the SHA-256.

## Measured

On 2026-11-18, on a machine with 4 cores: `OP-10` shortened to eight simulated hours, `static_allowlist`, the hostile agent, `--tier full`. All 31 proposals were judged, each replayed to the end, four hours on average.

| `--replay-jobs` | Wall time | SHA-256 of the card |
| --- | --- | --- |
| 1 | 272 s | `540a3f2f…deab4b93` |
| 3 | 200 s | `540a3f2f…deab4b93`, the same file |

- **The cards are the same file.**
- **The gain was small, 1.4 times with three helpers, because the branches were short.** Of the 200 s, about half went to asking the oracle what it judges. Building and warming up a plant takes about 2.7 s, as much as two simulated hours of a branch, and that step does it once for every branch. From this run the rule of six hours under decision 4 was set, and this run would no longer be shared.
- **What it suggests for a whole week, not measured:** one run of `OP-10` with the hostile agent under `static_allowlist` is about 670 branches of 84 simulated hours. At the rate of this run, about 1.4 s for a simulated hour, that is near a day in one process, and a few hours with five helpers. A gate that keeps state costs more.

## Not verified

- **The REMORA gates.** They are restored from their own snapshots, a path the tests cover with a stand-in gate. REMORA was not installed where this was written, so no REMORA gate has been judged this way.
- **A whole `full` run.** Neither its time nor its memory has been measured with replay jobs. While the oracle chooses what is judged, the asking process holds a capture for every proposal of the run, as a `full` run in one process does.
- **Windows and macOS.** Helpers are started the way `--jobs` starts its processes, which works on all three. Only Linux was tried.

## Consequences

- A `full` run with replay jobs is made with this code, not with the code at the tag of the season. Its card names the frozen benchmark version, because the hashes are the same, and its record (`bench record`, ADR 0025) names the commit.
- The next benchmark version should move the sharing into the oracle, so that its hash covers the code that plays the branches.
- A served gate is asked by several helpers at a time, as it already is with `--jobs`.
