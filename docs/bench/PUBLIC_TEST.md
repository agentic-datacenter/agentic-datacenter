# Public test

How a governance gate from any project is tested on Agentic-Datacenter in the open, and what makes the result worth something. The question, hypotheses and analysis are those of the [preregistration](PREREGISTRATION.md); this page is the procedure.

## Seasons

A public test runs in seasons. A season fixes three things before any participant can know the held-out scenarios:

1. **A frozen benchmark version.** `agentic-datacenter bench freeze` writes `docs/bench/VERSION.json`, the hashes of the profile, contracts, scenarios and oracle, and the version is tagged. A card from any other version is refused for the season.
2. **A beacon round.** The secret that draws the held-out variants of Track D is the output of the drand "quicknet" public randomness beacon at a round chosen and published here in advance, at least two weeks after the season opens. No one, the authors of Agentic-Datacenter included, can know it before the round is emitted; afterwards anyone can fetch it and check it (`tools/heldout_beacon.py`).
3. **A registration deadline**, the time the round is emitted. A gate takes part in the season's Track D only if it was registered before then, with the exact version it will run.

| Season | Frozen version | Beacon round | Emitted (UTC) | Status |
| --- | --- | --- | --- | --- |
| 1 | not frozen yet | not chosen yet | | Preparing |

## Taking part

1. **Check your gate.** `agentic-datacenter gate check <gate>` (see [Test your own gate](../guides/bring-your-own-gate.md)).
2. **Register it before the round** with the "Gate registration" issue form: the gate's name, how it is attached, and the commit, package hash or container digest that will be run. The time of the issue is the record. A gate changed after the round is a different gate.
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

Seed 1 of every season is also run by the maintainers with `--tier full`, to measure what the bounded replay misses. The comparison is published with the season.

## Reproduction

A result card is the same, byte for byte, for the same frozen version, gate, agents and seeds, whatever the machine and the number of processes (`ADC-BEN-006`). A result counts as reproduced when someone other than the gate's authors makes a card with the same SHA-256. Every participant who runs a built-in gate beside their own therefore also reproduces part of the benchmark on a second machine, which the preregistration asks for before any result is published.

A gate that is not deterministic, or a served gate that keeps state between runs, cannot be reproduced; its card says what it says once.

## What a season does not settle

- The scenarios of the public tracks are in this repository, and a gate may have been tuned to them. Only Track D is held out.
- The simulator, contracts and oracle are written by Agentic-Datacenter's authors. A gate written by them is reported apart from the others.
- A card is a simulation result. It says nothing about a real facility.
