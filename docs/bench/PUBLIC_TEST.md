# Public test

[![Agentic-Datacenter public test: register your gate](../media/season1-register-banner.webp)](https://github.com/darklordVirtual/agentic-datacenter/issues/new?template=gate-registration.yml)

**Registration is always open.** Seasons follow one another, four weeks each, on a frozen benchmark. [Register your gate](https://github.com/darklordVirtual/agentic-datacenter/issues/new?template=gate-registration.yml) with three fields; installation and the interface check can follow. The [calendar](#seasons) says when the open season closes.

How a governance gate from any project is tested on Agentic-Datacenter in the open, and what makes the result worth something. The question, hypotheses and analysis are those of the [preregistration](PREREGISTRATION.md); this page is the procedure.

## Seasons

A public test runs in seasons, one after another without a gap, so a season is always open.

- **Season 1** was opened by hand on 2026-11-17 and closes on 2026-12-02 at 12:00 UTC.
- **Every later season** opens at the instant the one before it closes, and closes four weeks later at 12:00 UTC.

A season fixes three things before any participant can know its held-out scenarios:

1. **A frozen benchmark version.** `agentic-datacenter bench freeze` writes the hashes of the profile, contracts, scenarios and oracle to a file, and the version is tagged. A season uses the version that is frozen when it opens. Today that is `benchmark-v1` ([VERSION.json](VERSION.json)). A new version is named in `seasons.json`, with the season it first applies to, before that season opens. A card from any other version is refused for the season.
2. **A beacon round.** The secret that draws the held-out variants of Track D is the output of the drand "quicknet" public randomness beacon at the round emitted when the season closes. The rounds of the coming year are in the calendar below, so each is published long before it exists. No one, the authors of Agentic-Datacenter included, can know it before the round is emitted; afterwards anyone can fetch it and check it (`tools/heldout_beacon.py`).
3. **A registration deadline**, the instant the round is emitted. A gate takes part in a season's Track D only if it was registered before then, with the exact version it will run.

<!-- seasons: made by tools/season.py from docs/bench/seasons.json; do not edit -->
| Season | Opens (UTC) | Registration closes and the round is emitted (UTC) | Beacon round | Benchmark version |
| --- | --- | --- | --- | --- |
| 1 | 2026-11-17 | 2026-12-02 12:00 | `34469812` | `benchmark-v1` |
| 2 | 2026-12-02 12:00 | 2026-12-30 12:00 | `35276212` | `benchmark-v1` |
| 3 | 2026-12-30 12:00 | 2027-01-27 12:00 | `36082612` | `benchmark-v1` |
| 4 | 2027-01-27 12:00 | 2027-02-24 12:00 | `36889012` | `benchmark-v1` |
| 5 | 2027-02-24 12:00 | 2027-03-24 12:00 | `37695412` | `benchmark-v1` |
| 6 | 2027-03-24 12:00 | 2027-04-21 12:00 | `38501812` | `benchmark-v1` |
| 7 | 2027-04-21 12:00 | 2027-05-19 12:00 | `39308212` | `benchmark-v1` |
| 8 | 2027-05-19 12:00 | 2027-06-16 12:00 | `40114612` | `benchmark-v1` |
| 9 | 2027-06-16 12:00 | 2027-07-14 12:00 | `40921012` | `benchmark-v1` |
| 10 | 2027-07-14 12:00 | 2027-08-11 12:00 | `41727412` | `benchmark-v1` |
| 11 | 2027-08-11 12:00 | 2027-09-08 12:00 | `42533812` | `benchmark-v1` |
| 12 | 2027-09-08 12:00 | 2027-10-06 12:00 | `43340212` | `benchmark-v1` |
| 13 | 2027-10-06 12:00 | 2027-11-03 12:00 | `44146612` | `benchmark-v1` |
<!-- /seasons -->

- **Which season is open now:** `python tools/season.py current`. The page is not rewritten when a season ends.
- **Where it comes from:** `docs/bench/seasons.json` holds the first deadline, the length of a season and the benchmark versions. The calendar is made from it, and a test fails if the two differ.
- **Check a round's time yourself:** `python tools/heldout_beacon.py round-at 2026-12-02T12:00:00Z`.

**What counts as registered.**

- An issue opened with the registration form takes part in the season that is open when it is opened, and in every season after it for as long as the issue stays open. Close the issue to leave.
- The version that counts for a season is the one the issue names at that season's deadline. GitHub keeps every edit of an issue, so that version is read from the issue's history, not from the issue as it is later.
- Whether an issue was open at a deadline is read from its close and reopen events, not from whether it is closed today. An issue closed at the deadline and opened again later did not take part.
- Nothing is guessed. If the text or the state of an issue at the deadline cannot be established from its history, the issue is listed with that said and without a version: an entry removed from the edit history, or a history that does not hold the whole text after each edit. The list carries the SHA-256 of each text it read.
- Right after a deadline the maintainers run `python tools/season_registrations.py --season <n>` and commit the list it writes, `docs/bench/season-<n>-registrations.json`. Anyone can run it again and get the same list.
- The built-in gates are registered by what the frozen version pins: `REMORA_PIN` and the code at the version's tag.

**What a season does not do by itself.** The calendar needs no one. The work of a season does: listing the registrations after the deadline, the maintainers' own runs, and publishing the results. A season nobody reported a result for has an empty result list, and that is said.

## Taking part

1. **Register a fixed version first.** Use the [gate registration form](https://github.com/darklordVirtual/agentic-datacenter/issues/new?template=gate-registration.yml). Only three fields are required: project name, exact immutable version (full commit SHA, package hash or image digest), and intended connection method (choose "not sure" if needed). You do **not** need to install anything or paste test output to register. You may change the version until the deadline; the one the issue names at the deadline is the one that runs in Track D.
2. **Connect and check your gate later.** Run `agentic-datacenter gate check <gate>` (see [Test your own gate](../guides/bring-your-own-gate.md)), and add the output and operating profile to your issue before submitting a result. A registration alone is not a passing check or a benchmark result. If integration changes the version you registered, update it **before** the deadline to remain eligible for Track D.
3. **Run the public tracks at any time** on the frozen version:

    ```sh
    uv run agentic-datacenter bench run --tier season --gate <gate> --gate static_allowlist --jobs 8 --out build/season1
    ```

    The 30 seeds can be split over machines with `--first-seed` and `--seeds`, and the parts merged with `agentic-datacenter bench merge` ([Tiers](TIERS.md)). To try a gate first, use `--tier quick`. A card from `--tier standard` is seeds 1 to 3 of the season, and can be checked against them.

4. **Run Track D after the round:**

    ```sh
    python tools/heldout_beacon.py secret --round <round> --out build/heldout.secret
    uv run agentic-datacenter bench run --tier season --gate <gate> --jobs 8 \
        --heldout-secret-file build/heldout.secret --out build/season-d
    uv run agentic-datacenter bench check build/season-d/result_card.json --gate <gate>
    ```

5. **Check it for publication:** `uv run agentic-datacenter bench check <card> --gate <gate> --publication`. It refuses an incomplete card and one not of the frozen version.
6. **Report it** with the "Gate result" issue form.

**The full-replay check is the maintainers' work, not a participant's.**

- The maintainers run seed 1 of every season with `--tier full`, on a machine of their own, for the built-in gates `static_allowlist` and `remora_governed` at least: one gate that keeps no state and one that does.
- What is published with the season is the comparison: for each proposal, whether the bounded replay and the replay to the end gave it the same label. It checks the season's bounds. It is not a result of a gate and is ranked nowhere.
- A participant is not asked to run `full`, and it is no condition for a result.
- The maintainers do not run a participant's gate. Nothing of a participant's runs on the maintainers' machine: every card is made by whoever reports it, and checked by its SHA-256 (see Reproduction).
- A participant who wants the same check for their own gate can run `--tier full --seeds 1 --replay-jobs <n>` and attach the card. It is published beside their result and changes nothing in it.

## Built-in gates

| Gate | Project | Profile |
| --- | --- | --- |
| `null_gate` · `static_allowlist` | baselines: no gate; role and range checks | `UNGOVERNED` · `STATIC_ALLOWLIST` |
| `remora` · `remora_governed` · `remora_shadow` | REMORA, pinned in `REMORA_PIN` | `DECISION_ONLY` · `GOVERNED` · `SHADOW` |

The built-in gates are written by Agentic-Datacenter's authors and are reported apart from the others. So far they have development runs only.

## Reproduction

A result card is the same, byte for byte, for the same frozen version, gate, agents and seeds, whatever the machine and the number of processes (`ADC-BEN-006`). A result counts as reproduced when someone other than the gate's authors makes a card with the same SHA-256. Every participant who runs a built-in gate beside their own therefore also reproduces part of the benchmark on a second machine, which the preregistration asks for before any result is published.

A gate that is not deterministic, or a served gate that keeps state between runs, cannot be reproduced; its card says what it says once.

## What a season does not settle

- The scenarios of the public tracks are in this repository, and a gate may have been tuned to them. Only Track D is held out.
- The simulator, contracts and oracle are written by Agentic-Datacenter's authors. A gate written by them is reported apart from the others.
- A card is a simulation result. It says nothing about a real facility.
