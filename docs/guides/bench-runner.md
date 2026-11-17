# Run long benchmarks on a machine of your own

A `standard` run of one gate took 59 minutes on a machine with 16 threads, and needed about 14 GB of memory. A `season` or `full` run has not been timed: `season` makes ten times the runs, and `full` replays every proposal to the end of its scenario ([what it costs](../bench/TIERS.md#what-it-costs)). A spare machine registered as a self-hosted GitHub Actions runner can do it. Runs are started from anywhere and the result card comes back as an artifact.

## Start a run

```sh
gh workflow run bench-runner.yml -R darklordVirtual/agentic-datacenter -f tier=standard -f gates=remora_governed
gh run watch -R darklordVirtual/agentic-datacenter                       # follow it
gh run download -R darklordVirtual/agentic-datacenter <run-id>           # the card, report and check
```

| Input | Meaning |
| --- | --- |
| `tier` | `quick`, `standard`, `season` or `full` ([Tiers](../bench/TIERS.md)) |
| `gates` | the gates to run, separated by spaces |
| `scenario` | one scenario only, or empty for all 23 |
| `first_seed`, `seeds` | a part of a season, to be merged with the others (`agentic-datacenter bench merge`) |
| `jobs` | runs at a time; empty is every core but one |

The workflow (`.github/workflows/bench-runner.yml`) runs the benchmark and then the release check for each gate. It keeps the card, the report and the check's output for 90 days. It runs only when started by hand, never on a pull request.

## Set up the machine

Any of Linux, macOS or Windows can be used. On Windows, use WSL2 with Ubuntu, so the runner sees the same environment as on Linux. Only Linux can install the IEC 61850 package; on the others the workflow leaves it out, and those scenarios run without it.

1. Install `git`, the GitHub CLI (`gh`) and [uv](https://docs.astral.sh/uv/). uv fetches Python 3.12 itself when it is missing.
2. Sign in with `gh auth login`, as an account with admin access to the repository.
3. Register the runner with the label `bench`, from <https://github.com/darklordVirtual/agentic-datacenter/settings/actions/runners/new>, or with a token from `gh api -X POST repos/darklordVirtual/agentic-datacenter/actions/runners/registration-token --jq .token`. Then run:

   ```sh
   ./config.sh --url https://github.com/darklordVirtual/agentic-datacenter --token <token> --labels bench --unattended
   ```

4. Run it as a service (`./svc.sh install` and `./svc.sh start` on Linux and macOS), so it survives a restart.
5. Stop the machine from sleeping while it is plugged in.
6. Start a `quick` run of one scenario to check it all works.

## Memory

Memory no longer decides how many runs fit; cores do. Measured on 2026-11-17, at the `standard` tier with `remora_governed`, each run in a process of its own: one run of `OP-10` (a simulated week, 671 proposals, 16 judged) with the hostile agent peaked at 0.32 GB, and one with the careful agent at 0.14 GB. The other runs measured, `OP-10` shortened to a day and the whole of `AD-08` and `OP-08`, peaked at 0.12 to 0.16 GB. Allow 0.4 GB for each job: `jobs` at 15 needs about 6 GB.

Before that date one run of `OP-10` with the hostile agent held 3.3 to 3.8 GB and one with the careful agent about 1 GB, so nine at a time needed about 14 GB. The run kept a copy of the plant's state, with every record so far, at each of its 671 decision points, and for a gate that keeps state of its own it did so twice. It now keeps one only at the instants that are judged, and lets each go when its last branch has started. The cards are the same.

A gate that keeps no state of its own is judged from one run, which cannot know in advance which instants will be judged, and still keeps a copy at every decision point until the run ends: 0.8 GB for `OP-10` with the hostile agent under `static_allowlist` (1.1 GB before). With such a gate, allow 1 GB for each run of `OP-10` that is in memory at a time. The longest runs start first, so that is as many as there are jobs.

The figures are from a machine with 16 threads and 11 GB given to WSL2. On Windows, WSL2 gets half of the machine's memory unless `%UserProfile%\.wslconfig` says otherwise:

```ini
[wsl2]
memory=11GB
swap=8GB
```

## On a public repository

A self-hosted runner executes whatever a workflow asks of it. On a public repository a pull request from a fork can add or change a workflow, so a runner that accepts such a job runs a stranger's code on the machine. For as long as a runner is registered:

- Set **Settings → Actions → General → Fork pull request workflows** to require approval for all outside contributors, and do not approve a run of a pull request that touches `.github/workflows/`.
- Keep the label `bench` out of every other workflow, and keep `bench-runner.yml` started by hand only.

`tests/conformance/test_ci.py` (`test_the_benchmark_runner_is_started_by_hand_only`) enforces the second point in part. It fails when `bench-runner.yml` has a trigger other than `workflow_dispatch`, or when any other workflow file names a self-hosted runner. It reads the workflow files only. It cannot see the repository's settings, so the first point is not checked by anything in this repository.
