# ADR 0042: What is free to copy, and what a contribution asks of its author

- **Status:** Accepted on 2026-11-27. The owner decided both points, to make the threshold for taking part and contributing as low as it can be.
- **Date:** 2026-11-27
- **SDD:** 2; ADR 0004, 0022, 0034

## Context

The repository is under the Business Source License 1.1 (ADR 0004). That protects the simulator. It also covered, without anyone having meant it to, the things a system from elsewhere has to copy to take part: the wire format, the rule for signed mandate statements and its test vectors. A maintainer who wants those vectors in their own test suite could not tell whether they may ship them.

A scenario from outside met the other obstacle. The contribution terms of `CONTRIBUTING.md` let the Licensor relicense a change. That is right for a change to the simulator and wrong for a scenario someone proposes, as it was for a maker's equipment data (ADR 0034).

## Decision

1. **The interface is under the MIT licence.** `docs/reference/gate-http-v1.schema.json`, `docs/reference/mandate-statements.md` and `docs/reference/mandate-vectors.json`, named in `docs/reference/LICENSE`. With the examples, which were MIT already, everything a system needs to connect and to test its own implementation can be copied, changed and shipped.
2. **A scenario file proposed from outside is under CC-BY-4.0**, with its proposer named in the file's header. The contribution terms do not apply to it. The same terms as an equipment entry from a maker.
3. **A proposal in words asks for nothing.** The form grants no right and needs none.
4. **Three kinds of file can come as a pull request without the rules for code**: a scenario file, an equipment entry, and a correction to a page of documentation.

## What stays as it was

The simulator, the scenarios written by this project, the contracts, the judge and the tools are under the Business Source License 1.1. Running them to develop, test, evaluate or benchmark is free. A system that connects is its owner's, under its owner's licence.

## Consequences

- A participant's licence question has one short answer for each thing they touch: their system is theirs; the interface and the examples are MIT; a scenario or an equipment entry they give is CC-BY-4.0 with their name on it.
- The library will hold scenarios under two licences. A scenario's header says which, and a scenario with no such header is this project's own.
