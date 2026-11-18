# ADR 0027: Seasons follow one another by a rule

- **Status:** Proposed. Accepted when the PR that adds it is merged by the owner.
- **Date:** 2026-11-18
- **SDD:** 12.1; ADR 0023; `docs/bench/PUBLIC_TEST.md`, `docs/bench/PREREGISTRATION.md`

## Context

Season 1 was set up by hand: a frozen version, a beacon round, a deadline, and a README, a page and a form that all name them. When it closes on 2 December 2026 there is nothing to register for until someone sets up a second season the same way, and every text that names Season 1 is out of date.

A public test is worth more when a project that finds it in any week can enter. And a round is worth most when it is published long before it is emitted.

## Decision

1. **One rule gives every season.** Season 1 stands as published. Every later season opens at the instant the one before it closes, and closes four weeks later at 12:00 UTC. A season is always open.
2. **The round follows from the deadline.** A season's Track D secret is the drand quicknet round emitted at its deadline. The rule fixes every deadline, so it fixes every round. The first thirteen, a year of them, are published now.
3. **The plan is one small file,** `docs/bench/seasons.json`: the first deadline, the length of a season, how many seasons the page lists, and which benchmark version applies from which season. `tools/season.py` reads it. `current` says which season is open; `calendar --write` makes the table on the public-test page, and a test fails if the page and the plan differ.
4. **A season uses the benchmark version frozen when it opens.** A new version is entered in the plan, with the season it first applies to, before that season opens. A season never changes version.
5. **A registration stands until its issue is closed.** It counts for the season open when the issue is opened and for every season after, with the version the issue names at each deadline. `tools/season_registrations.py --season <n>` leaves out an issue closed by that season's deadline.
6. **Nothing that is not rewritten names a season.** The README and the registration form say that registration is always open and point to the calendar. A test keeps the number of a season, a date and a round out of both.

## What is not automatic

- **No job runs when a season ends.** Nothing has to: the calendar is a rule. A job that commits to the repository would need write access, and nothing here merges by itself.
- **The work of a season is still someone's.** Listing the registrations after the deadline is one command. The maintainers' own runs of the built-in gates, the full-replay check and publishing the results are not automated. A season with no reported result has an empty result list.
- **Four weeks is a commitment.** Each season asks the maintainers for a season of the built-in gates on Track D and one full-replay check. If that cannot be kept up, the length in the plan is changed for seasons that have not opened, and the change is entered in the preregistration.

## Consequences

- The banner image still reads "Season 1". It is an image and is not made by a tool; the text beside it is general.
- After thirteen seasons the number listed in the plan is raised. The rule does not end.
- Results are per season. Whether and how seasons are pooled is not decided here and would be entered in the preregistration first.
