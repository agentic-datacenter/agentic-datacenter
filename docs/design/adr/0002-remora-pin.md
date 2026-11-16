# ADR 0002: REMORA is one pinned commit, imported by one package

- **Status:** Proposed. Accepted when the Stage 0 PR is merged by the owner.
- **Date:** 2026-11-12
- **SDD:** 5.2, 9.2; requirements `ADC-PIN-001` to `-006`

## Context

Agentic Datacenter exists to measure governance gates, with REMORA as the first. Two runs are comparable only if they used the same REMORA. REMORA integrates on `dev` and is under active change, and the benchmark must also run with other gates and with no gate, so REMORA cannot be a dependency of the simulator as a whole.

## Decision

1. **First pin.** Tag `dcsim-pin-2026-11-12b`, commit `dfc44de2b4ebc579b0c5e76c541eeecd414961d6`. The earlier tag `dcsim-pin-2026-11-12` was superseded before any Agentic Datacenter code existed.
2. **What is recorded.** `REMORA_PIN` and `uv.lock` hold the full 40-character commit SHA. The tag name is recorded for people; the tag object's SHA is never used as the pin.
3. **How it is consumed.** As an ordinary Git dependency of `agentic-datacenter-remora`, resolved by `uv`. No submodule, no vendored copy.
4. **Isolation.** `agentic-datacenter-remora` is the only distribution that imports REMORA. It is not a default dependency of the workspace: it is installed through the `remora` dependency group. Everything else installs and passes its tests without it.
5. **Surface.** `agentic-datacenter-remora` imports from `remora.sdk` only.
6. **Bumps.** A pin bump is its own PR, changing only the pin and the lock.

## Verification at Stage 0

Recorded in full in `docs/design/remora_binding.md`. In short:

- Both tags and their commits match the SDD table; the pinned commit is on `dev`.
- The workspace locks and installs REMORA at the pinned SHA, and the installed distribution reports that SHA, which gives the run-time check for `ADC-PIN-003` something to read.
- The import contract "REMORA is imported only inside `agentic_datacenter_remora`" is in place and was shown to fail when a REMORA import is added to `agentic_datacenter.core`.
- The workspace installs and imports with REMORA absent.

## Consequences

- `agentic-datacenter-remora` needs REMORA's `security` and `sdk` extras, not `security` alone. This differs from SDD 5.2 and is proposed as an SDD change in `remora_binding.md`, section 3.1.
- Installing the `remora` group needs read access to the REMORA repository. Jobs and contributors without it can still build and test everything else.
- Stage 8 cannot start on this pin: it needs a pin that contains `remora build-toolspec`.
- The contract limiting `agentic_datacenter_remora` to `remora.sdk` (`ADC-PIN-005`) is added in Stage 8 with the binding code. The Stage 0 contract only keeps REMORA out of the other packages.
- REMORA is licensed under BUSL-1.1. What that means for Agentic Datacenter's own licence is part of ADR 0004.
