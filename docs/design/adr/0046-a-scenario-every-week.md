# ADR 0046: A scenario every week, sealed before it is shown

- **Status:** Superseded on 2026-11-27, the day it was accepted, by [ADR 0047](0047-drawn-from-a-beacon.md): a week's scenarios are drawn from a public beacon, and are not written, sealed or released by a person. What follows is the record of what was decided first. Accepted on 2026-11-27. The owner asked that new scenarios come once a week and that they can be preregistered, and that none of them is of a kind nobody can run.
- **Date:** 2026-11-27
- **SDD:** 12.1, 12.4; ADR 0023, 0036, 0043

## Context

A season freezes its scenarios for four weeks, so that every system is measured on the same ones. That is right for a result and wrong for learning: a maintainer who has passed the frozen set has nothing new to try until the next season, and a set that does not move is fitted to.

Scenarios on the main branch can move. But a scenario that appears without warning from the people who also maintain an enrolled system invites a fair question: was it written to suit that system, or changed after its results were seen?

## Decision

**One scenario for each Monday.** It is released at the start of the week, before the Monday run of the workflow that enrolled systems copy.

**Sealed at least three days before.** The SHA-256 of the scenario's file is committed to `weekly/register.yaml` with the Monday it is for. The file is kept back until then. The file's header says what the two reference controls are expected to do with it, so the expectation is sealed with it.

**Released as the file that was sealed.** On the Monday the file goes into `weekly/scenarios/`. `tools/weekly.py check` fails when a released file does not hash to what was sealed, when a file is there that was not sealed, or when an entry was sealed too late. It runs with the tests of every change.

**Short.** A weekly scenario lasts at most two simulated hours, which is under a minute for each control on a laptop. A scenario that plays out over a day, such as a long outage, belongs in a season and not in a week; the check refuses it.

**About one thing, with its own control.** It hands the agent a step that one kind of check stops, and the same kind of step when nothing forbids it.

**Outside the frozen version.** The files are not in the scenario library, so every hash of a frozen version is unchanged. A run of one is a development result. At the end of a season the scenarios released during it are candidates for the next version.

**A missed week is seen.** A scheduled workflow checks every Monday that the day's scenario was released and the next is sealed, and fails otherwise, which is sent to the maintainers. It writes nothing.

## Consequences

- An enrolled system meets something new every week with no work by its maintainers, and learns of a weakness before a season counts it.
- A proposal from outside has a date: it is answered within a week and, if it is taken, has a Monday.
- The seal shows when a scenario was fixed and that it was not changed. It does not show that its writers had no system in mind. Only scenarios written by others answer that.
- Releasing is a pull request by a person each Monday. The sealed files of the coming weeks are kept by the maintainer, outside the repository; if they are lost, those weeks are withdrawn in the register and say so.

## What it is not, yet

- **No release without a person.** A workflow could decrypt and release a file by itself. That needs a key held as a secret and a way past review, and is left until the rhythm has held for a season.
- **No table of weekly results.** A system's weekly runs are its maintainers' own. Whether to show them beside each other is a decision for when there are several.
