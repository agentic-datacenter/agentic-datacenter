# ADR 0025: A release and a result card can be traced to the commit and the job that made them

- **Status:** Proposed. Accepted when the PR that adds it is merged by the owner.
- **Date:** 2026-11-17
- **SDD:** 12.1, 12.4; requirement `ADC-CI-003`; ADR 0004, 0011

## Context

Two things are handed to people outside this project, and for neither could they check where it came from.

- **A release.** `release.yml` builds ten wheels and ten source distributions and uploads them. Nothing ties a file to the commit and the job that built it, and nothing lists what it depends on.
- **A result card.** The card names the benchmark version, which is a tuple of hashes of the profile, the scenarios, the oracle, the contracts and the agents. It does not name the commit of the code, and nothing says whether a card is the file a run wrote or one edited afterwards. An evidence bundle of one scenario run has a manifest with hashes (`scenario verify`); the directory a benchmark writes has none.

A reader of a result should not have to take the publisher's word for which simulator made it.

## Decision

1. **A record beside every result card.** `agentic-datacenter bench record <directory>` writes `provenance.json` in the directory a benchmark wrote: the schema `adc-provenance/v1`, the commit of the code (with `+dirty` when files differ from it), the benchmark version and the label of the card, and the SHA-256 of every other file in the directory. `agentic-datacenter bench verify <directory>` names every file that is changed, missing or added since, and a card whose benchmark version is not the record's.
2. **The record is evidence only when it is signed.** Anyone can write a record. On the benchmark runner, the job writes the record and then attests it: GitHub signs a statement, with a short-lived certificate from Sigstore issued to that workflow run, that this file with this digest was made by this workflow at this commit. `gh attestation verify provenance.json --repo <owner>/<repository>` checks it.
3. **A release is attested the same way.** After the licence check, the release job writes a bill of materials from the lock (`uv export --format cyclonedx1.5`, so no new tool), and attests every wheel and source distribution twice: once with the build provenance GitHub generates, once with the bill of materials.
4. **One action, pinned.** `actions/attest` at the commit of v4.2.2, as every third-party action is pinned (`ADC-CI-003`). Only the two attesting jobs get `id-token: write` and `attestations: write`; every other job stays read-only, and a conformance test keeps it so.
5. **No new dependency and no key of our own.** The record is made with the standard library. Signing uses the identity of the workflow run, so there is no private key to keep, lose or rotate.

## What this does not show

- **Not that a result is right.** An attestation says where a file came from. Whether the simulator is a good model of a facility is a separate question (SDD section 14).
- **Not that the machine was clean.** The benchmark runner is a self-hosted machine. The attestation says which workflow run on it produced the record, not that nobody altered that machine. A run on a hosted runner would say more.
- **Not who owns what.** A signed record is not a statement of copyright and does not replace `LICENSE`.
- **A development run stays a development run.** A record of an unfrozen run carries the label of the card. Attesting it does not make it a benchmark result.

## Not verified

- **No attestation has been made.** The steps run on a public repository only, because a private repository of a personal account cannot store attestations, and this repository was private when they were written. The workflow files are checked by `tests/conformance/test_attestations.py`; the first run on a public repository is the first real test.
- **The bill of materials was made with uv 0.11.32 on a development machine.** Whether the uv in the reference image knows `--format cyclonedx1.5` has not been checked. If it does not, the release job fails at that step, before anything is attested or uploaded.

## Left out

- **Signed licence certificates for commercial customers.** There is no commercial customer and no feature that a certificate would unlock. It is licence enforcement, not provenance, and would be its own decision.
- **A register of sources that are not public.** It cannot be kept in a public repository. `THIRD_PARTY_NOTICES.md` says that not everything consulted is public.
- **A record written by `bench run` itself.** The command stays separate, so that a card merged from parts (`bench merge`) is recorded once, after the merge.
