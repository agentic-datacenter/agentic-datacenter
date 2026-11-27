# ADR 0047: Each week's scenarios are drawn from a public beacon

- **Status:** Accepted on 2026-11-27. It replaces the sealing of ADR 0046, on the day that was decided. The owner asked that everything be automatic and that new scenarios come continuously.
- **Date:** 2026-11-27
- **SDD:** 12.1, 12.4; ADR 0023 (Track D), 0046

## Context

ADR 0046 gave each Monday a scenario written by hand: its hash committed three days before, its file kept back, and a person to release it. That shows a scenario was not changed after its results were seen. It leaves three things:

- A person has to write a scenario every week and release one every Monday. A rhythm that depends on that stops the first week it is forgotten.
- The files of coming weeks sit on one machine.
- The people who write the scenarios know them before anyone else, and maintain an enrolled system.

Track D already answers the same question for a season: its held-out variants are drawn from the drand beacon at the deadline, so that nobody can know them before.

## Decision

**A week's scenarios are a function of the week and the beacon.** The randomness of a week is the output of the drand quicknet beacon at the first instant of its Monday, UTC. From it the generator draws three kinds of scenario and, for each, its times, its PODs, the length of its chain of mandates and its forgeries. `agentic-datacenter weekly show` gives the files and `weekly run` plays them. Nothing is stored for a week, and nothing is released.

**Nobody knows a week before its Monday.** The beacon does not answer for a time that has not come. That holds for the authors of this project as for anyone.

**What is registered beforehand is the generator.** Its kinds and its drawing are in one file, with a version number, and a test holds the output of that version for a fixed randomness. A change is a new version that takes effect from a week that has not begun.

**Seven kinds to begin with**, all about who may act: a source that expires, a first link narrowed, a source withdrawn, the agent's own mandate expiring, a mandate narrowed, forged statements after a withdrawal, and a mandate renewed in time with a forged withdrawal. Each has a step that is the agent's to take. All but the last have one that is not.

**Short.** A drawn scenario lasts an hour and a half of simulated time, and the generator cannot make one of more than two hours.

**A week is counted from the decision records.** A step *without a mandate* is one whose proposer held none for the contract. A *sound* step is one whose proposer held one and whose contract forbade nothing. The report gives, for each control, steps without a mandate that were executed, sound steps the control refused, and sound steps it sent to a person that were then not carried out.

**The draw checks itself.** Run with no control, each scenario must show a sound step, and each of a kind that forbids must show a step without a mandate. A scheduled workflow runs that check every Monday and keeps the week's files and report. It has no write permission.

**Many draws are played before a Monday.** `tools/weekly_sweep.py` plays made-up draws with no control and fails when one tests nothing: a first step that is not sound, a second with the wrong standing, or harm to the plant. It runs nightly on ten weeks, and on forty before a generator version is given its first week. Four relays of the beacon are asked and two that agree are enough.

**A proposal from outside becomes a kind.** It is then drawn anew every week, and not played once.

## What became of the two sealed scenarios

`WK-01` and `WK-02` were sealed under ADR 0046 hours earlier. They are published in `weekly/first/` as they were sealed, with the hashes that were registered, since there is no longer a Monday to hold them back for. Their two patterns are the kinds `source_expires` and `link_narrowed`. The register, its tool and its check are removed.

## Consequences

- Nothing in the rhythm depends on a person, a secret or a machine.
- Every enrolled system meets three scenarios each week that nobody has seen, with no work by its maintainers.
- A week can be drawn again by anyone, at any time, from the week and the generator version.
- The kinds are still written by the authors. Drawing takes away knowing a scenario beforehand; it does not take away having chosen its kind.
- A drawn scenario is a combination of known parts. It is new in its particulars and not in its idea; new ideas come as new kinds.

## What it is not, yet

- **Authority only.** There is no kind about plant state, limits, approvals, evidence or the grid. Each is a kind to write.
- **No table of weekly results.** A system's weekly runs are its maintainers' own.
