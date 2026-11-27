# A new scenario every week

A benchmark that stands still is learned by heart. So every Monday one new scenario is released, and it was sealed before anyone saw it.

## What you do

Nothing, if you copied [the workflow](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/examples/ci/agentic-datacenter.yml): its Monday run plays the weekly scenarios against your system on the main branch, beside the two reference controls, and a result there never breaks your build.

By hand, with any control:

```sh
git pull
for f in weekly/scenarios/WK-*.yaml; do
  uv run agentic-datacenter scenario run "$f" --gate static_allowlist --out "build/weekly/$(basename "$f" .yaml)"
done
```

About twenty seconds for each scenario and control on a laptop.

## What a weekly scenario is

- **Short.** At most two simulated hours, and under a minute to run for each control. Nothing that plays out over a day, and nothing that needs a machine you do not have.
- **About one thing.** It hands the agent a step that only one kind of check stops, and the same kind of step when nothing forbids it. A control that lets the first through missed something; one that refuses the second is strict in the wrong place.
- **Not a trap for one system.** Nothing only one system could pass, and nothing written with one system's results in view.
- **Proposed by anyone.** [In words](../guides/propose-a-scenario.md). A proposal is answered within a week, and its proposer is named if they ask to be.

## Sealed before it is shown

A scenario could be written to suit a system, or changed after its results were seen. So that neither can be done unseen:

1. The scenario is written and tried. The SHA-256 of its file goes into [`weekly/register.yaml`](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/weekly/register.yaml), with the Monday it is for, at least three days before that Monday. The file is kept back.
2. The file's own header says what the two reference controls are expected to do with it.
3. On the Monday the file is put into `weekly/scenarios/`. It hashes to what was sealed, and a check in this repository fails if it does not.

Anyone can check it: `sha256sum weekly/scenarios/WK-01.yaml`, and `git log -S <hash> -- weekly/register.yaml` for the day the hash was committed.

What this does not show: that the people who wrote the scenario did not have a system of their own in mind. The project's authors maintain one of the enrolled systems, and they write most of the scenarios until others do. The seal shows when a scenario was fixed, and that it was not changed afterwards. The remedy for the rest is scenarios from outside.

## How it stands to a season

A weekly scenario is on the main branch only. It is no part of a frozen benchmark version, and a run of it is a development result, not a benchmark result. When a season ends, the scenarios released during it are candidates for the next frozen version, which is then preregistered as a whole. Nothing changes in the middle of a season.

## If a Monday is missed

A workflow in this repository checks every Monday that the scenario of the day was released and that the next one is sealed, and fails when either is not so, which is sent to the maintainers. A week without a scenario is in the register as such, and is not filled in afterwards.

## The register today

| Week of | Scenario | Family | Proposed by | State |
| --- | --- | --- | --- | --- |
| 2026-11-30 | `WK-01` | Authority | The project | Sealed on 2026-11-27 |
| 2026-12-07 | `WK-02` | Authority | The project | Sealed on 2026-11-27 |
| 2026-12-14 | `WK-03` | Authority | [aeoess](https://github.com/agentic-datacenter/agentic-datacenter/issues/76) | Planned |

The register itself is the record; this table is kept by hand.
