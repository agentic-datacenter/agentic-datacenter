# Public test

[![Agentic-Datacenter Season 1 Public Test](../media/season1-register-banner.webp)](https://github.com/darklordVirtual/agentic-datacenter/issues/new?template=gate-registration.yml)

**Season 1 is open · 2 December 2026, 12:00 UTC deadline · `benchmark-v1`.** [Register your gate](https://github.com/darklordVirtual/agentic-datacenter/issues/new?template=gate-registration.yml) with three fields; installation and the interface check can follow.

How a governance gate from any project is tested on Agentic-Datacenter in the open, and what makes the result worth something. The question, hypotheses and analysis are those of the [preregistration](PREREGISTRATION.md); this page is the procedure.

## Seasons

A public test runs in seasons. A season fixes three things before any participant can know the held-out scenarios:

1. **A frozen benchmark version.** `agentic-datacenter bench freeze` writes `docs/bench/VERSION.json`, the hashes of the profile, contracts, scenarios and oracle, and the version is tagged. A card from any other version is refused for the season.
2. **A beacon round.** The secret that draws the held-out variants of Track D is the output of the drand "quicknet" public randomness beacon at a round chosen and published here in advance, at least two weeks after the season opens. No one, the authors of Agentic-Datacenter included, can know it before the round is emitted; afterwards anyone can fetch it and check it (`tools/heldout_beacon.py`).
3. **A registration deadline**, the time the round is emitted. A gate takes part in the season's Track D only if it was registered before then, with the exact version it will run.

| Season | Frozen version | Beacon round | Emitted (UTC) | Status |
| --- | --- | --- | --- | --- |
| 1 | `benchmark-v1` ([VERSION.json](VERSION.json)) | `34469812` | 2026-12-02 12:00 | Open: register before the round |

Check the round's time yourself with `python tools/heldout_beacon.py round-at 2026-12-02T12:00:00Z`.

**What counts as registered.** The issue must be opened before the deadline, and the version that counts is the one the issue names at the deadline. GitHub keeps every edit of an issue, so that version is read from the issue's history, not from the issue as it is later: right after the deadline the maintainers run `python tools/season_registrations.py --deadline 2026-12-02T12:00:00Z --out docs/bench/season-1-registrations.json` and commit the list. Anyone can run it again and get the same list. The built-in gates are registered by what the frozen version pins: `REMORA_PIN` and the code at the tag `benchmark-v1`.

## Taking part

1. **Register a fixed version first.** Use the [Season 1 gate registration form](https://github.com/darklordVirtual/agentic-datacenter/issues/new?template=gate-registration.yml). Only three fields are required: project name, exact immutable version (full commit SHA, package hash or image digest), and intended connection method (choose "not sure" if needed). You do **not** need to install anything or paste test output to register. You may change the version until the deadline; the one the issue names at the deadline is the one that runs in Track D.
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
        --heldout-secret-file build/heldout.secret --out build/season1-d
    uv run agentic-datacenter bench check build/season1-d/result_card.json --gate <gate>
    ```

5. **Check it for publication:** `uv run agentic-datacenter bench check <card> --gate <gate> --publication`. It refuses an incomplete card and one not of the frozen version.
6. **Report it** with the "Gate result" issue form.

**The full-replay check is the maintainers' work, not a participant's.**

- The maintainers run seed 1 of every season with `--tier full`, on a machine of their own, for the built-in gates `static_allowlist` and `remora_governed` at least: one gate that keeps no state and one that does.
- What is published with the season is the comparison: for each proposal, whether the bounded replay and the replay to the end gave it the same label. It checks the season's bounds. It is not a result of a gate and is ranked nowhere.
- A participant is not asked to run `full`, and it is no condition for a result.
- The maintainers do not run a participant's gate. Nothing of a participant's runs on the maintainers' machine: every card is made by whoever reports it, and checked by its SHA-256 (see Reproduction).
- A participant who wants the same check for their own gate can run `--tier full --seeds 1 --replay-jobs <n>` and attach the card. It is published beside their result and changes nothing in it.

## Reproduction

A result card is the same, byte for byte, for the same frozen version, gate, agents and seeds, whatever the machine and the number of processes (`ADC-BEN-006`). A result counts as reproduced when someone other than the gate's authors makes a card with the same SHA-256. Every participant who runs a built-in gate beside their own therefore also reproduces part of the benchmark on a second machine, which the preregistration asks for before any result is published.

A gate that is not deterministic, or a served gate that keeps state between runs, cannot be reproduced; its card says what it says once.

## What a season does not settle

- The scenarios of the public tracks are in this repository, and a gate may have been tuned to them. Only Track D is held out.
- The simulator, contracts and oracle are written by Agentic-Datacenter's authors. A gate written by them is reported apart from the others.
- A card is a simulation result. It says nothing about a real facility.
