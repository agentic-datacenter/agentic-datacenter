# Run long benchmarks on a machine of your own

A `standard`, `season` or `full` run takes hours. A spare machine registered as a self-hosted GitHub Actions runner can do it. Runs are started from anywhere and the result card comes back as an artifact.

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

The long runs need memory as well as cores. In a `standard` run of `remora_governed`, one run of `OP-10` with the hostile agent held 3.3 to 3.8 GB, one with the careful agent about 1 GB, and the other scenarios 0.1 to 0.2 GB each. The longest runs start first, so with `jobs` at 9 or more all nine runs of `OP-10` are in memory together: about 14 GB at the peak, 35 minutes in.

That was measured on a machine with 16 threads and 11 GB given to WSL2, with 8 GB of swap. The run finished in 59 minutes, but it used 5 GB of the swap. With less than 16 GB free, set `jobs` lower: 6 keeps at most six runs of `OP-10` in memory. On Windows, WSL2 gets half of the machine's memory unless `%UserProfile%\.wslconfig` says otherwise:

```ini
[wsl2]
memory=11GB
swap=8GB
```

## Before the repository is public

A self-hosted runner executes whatever a workflow asks of it. This workflow only starts by hand, but on a public repository any workflow a pull request adds could run on the machine. Before the repository is made public:

- set **Settings → Actions → General → Fork pull request workflows** to require approval for all outside contributors;
- keep the runner's label `bench` out of every other workflow.
