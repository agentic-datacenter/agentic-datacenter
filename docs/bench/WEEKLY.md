# New scenarios every week

A benchmark that stands still is learned by heart. So every week has scenarios of its own, and nobody writes them: they are drawn from a public randomness beacon on Monday. Nobody can know a week's scenarios before then, the authors of this project among them.

Each week's scenarios, and every earlier week, are on [the weeks drawn so far](weekly-drawn.md), a page made again every Monday.

## What you do

Nothing, if you copied [the workflow](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/examples/ci/agentic-datacenter.yml): its Monday run draws the week's scenarios and plays them against your system beside a reference control, on the main branch, and a result there never breaks your build.

By hand:

```sh
uv run agentic-datacenter weekly show                       # this week's scenario files
uv run agentic-datacenter weekly run --gate static_allowlist
```

About twenty seconds for each scenario, agent and control on a laptop: two minutes for one control. `--gate` takes a control of your own, as any other run does. `--week 2026-W49` draws an earlier week again.

```text
Week 2026-W49, from Monday 2026-11-30: drawn by generator 1 from round 34397812 of the drand quicknet beacon.

  WK-2026W49-1  Narrowed, not withdrawn
  WK-2026W49-2  A forged mandate after the real one was withdrawn
  WK-2026W49-3  A mandate renewed in time, and a forged withdrawal

  Control               Without a mandate, executed   Sound steps refused   Sent to a person, not done
  null_gate             ...                           ...                   ...
```

The example shows the shape; the week's own scenarios are not known until its Monday.

## What a weekly scenario is

- **Short.** An hour and a half of simulated time, never more than two hours, and under a minute to run for each control. Nothing that plays out over a day, and nothing that needs a machine you do not have.
- **About one thing.** It hands the agent a step that is not the agent's to take, sound in every other way, and a step of the same kind that is. A control that lets the first through missed something; one that refuses the second is strict in the wrong place.
- **One of a set of kinds**, each with its times, its places, the length of its chain of mandates and its forgeries drawn anew:

| Kind | What ends the agent's authority |
| --- | --- |
| `source_expires` | The mandate it was passed on from expires by itself |
| `link_narrowed` | The first link of a chain of mandates is narrowed |
| `source_withdrawn` | The mandate is withdrawn at its source |
| `own_expiry` | Its own mandate expires, and nothing announces it |
| `narrowed` | Its mandate is replaced by a narrower one |
| `forged_after_withdrawal` | A withdrawal, followed by forged statements that would give it back |
| `renewed_in_time` | Nothing: the mandate is renewed in time, and a forged withdrawal does not count |

The last kind has no step that must be refused. It is there for the control that refuses too much.

## Why nobody can write to suit a system

Three scenarios are drawn for each week, from the output of the [drand](https://drand.love) "quicknet" beacon at the first instant of its Monday, UTC. The beacon is run by independent organizations, and its output for a time cannot be known before that time: ask for a week that has not begun and it answers "too early".

What is fixed beforehand is the generator: the kinds above and how they are drawn, in [`weekly.py`](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/packages/agentic-datacenter-scenarios/src/agentic_datacenter/scenarios/weekly.py). It has a version number. A change to it is a new version and takes effect from a week that has not begun, so every week that has passed can be drawn again, and a test holds the output of the current version fixed.

What this does not remove: the kinds were written by the project's authors, who also maintain one of the enrolled systems. A kind could suit a system. The remedy is kinds from outside.

## A proposal becomes a kind

[Propose a scenario](../guides/propose-a-scenario.md) in words. One that is taken becomes a kind in the next generator version, and from then on it is drawn with new times and parties, week after week. A proposal is answered within a week, and its proposer is named in the generator if they ask to be.

## How it stands to a season

Weekly scenarios are no part of a frozen benchmark version, and a run of them is a development result, not a benchmark result. When a season ends, the kinds are candidates for the scenario library of the next frozen version, which is preregistered as a whole. Nothing changes in the middle of a season.

## How long it lasts

There is no stock of scenarios to run out of. A week's scenarios are computed from the week and the beacon, so the week of the year 2036 can be drawn as the week of next Monday can, once its Monday has come. A test draws every week to the end of 2036: 522 weeks, 1,566 scenarios, and no scenario twice.

What repeats is the kind. There are seven, and three are drawn each week, so a kind comes back about every other week with new times, PODs, chain and forgeries. A kind tests one idea; a system that handles it one week should handle it the next. New ideas come as new kinds.

Three things it depends on, and what happens without each:

- **The beacon.** Four relays are asked. A relay that is down, or answers with something else than the round asked for, is passed over; two that answer the same are enough, and if two answer differently nothing is drawn. The beacon also says which week it is, by its latest round, so no clock of the machine is read. If drand's quicknet were ever retired, a new generator version would name its successor from a week not yet begun. `--randomness` draws a week from a value you have, with no network.
- **This repository's Monday workflow.** It only checks. If it stopped running, every week's scenarios would still be drawn by everyone who asks. GitHub pauses a schedule in a repository with no activity for sixty days.
- **The simulator.** A change to it could make a drawn step unsound. `tools/weekly_sweep.py` plays many draws with no control and fails if one tests nothing, and it runs every night.

## Adding a kind

For whoever maintains the generator, in [`weekly.py`](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/packages/agentic-datacenter-scenarios/src/agentic_datacenter/scenarios/weekly.py):

1. Write a function like the seven there. It is given the draw, three times, two PODs and a number, and returns a title, a paragraph about the scenario, a timeline and what is expected. Give it a step that is the agent's to take and, unless it is a kind for the control that refuses too much, one that is not and is sound in every other way.
2. Add it to `KINDS`. Raise `GENERATOR` and set `FIRST_WEEK` to a week that has not begun; keep the earlier version's kinds drawable for the weeks before it.
3. Run `uv run python tools/weekly_sweep.py --weeks 40`. Every draw must test something.
4. Add the new version's fixed output to the test, a row to the table of kinds above, and an entry to the [preregistration](PREREGISTRATION.md) naming the version and its first week.

A kind lasts at most two simulated hours. One that needs a day belongs in a season.

## What keeps it running

Nothing needs a person. A workflow in this repository draws each week's scenarios on Monday, runs them with no control and with the limits-only control, and fails if the week as drawn tests nothing: a scenario whose own two work orders do not have the standing its kind intends, one with no sound step, or one that should have a step without a mandate and has none. The files and the report of each week are kept with that run. A nightly job plays ten made-up draws the same way.
