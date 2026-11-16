# ADR 0005: Workspace layout and layer import contracts

- **Status:** Proposed. Accepted when the Stage 0 PR is merged by the owner.
- **Date:** 2026-11-12
- **SDD:** 5 (distribution table and repository layout), 12.4; requirements `ADC-MOD-002`, `ADC-PIN-001`, `ADC-CI-002`

## Context

The SDD ships Agentic Datacenter as eight distributions with a fixed "may import" rule for each, six of them under one import name, `agentic-datacenter`. Stage 0 has to turn that table into something a build can fail on, before there is any code to get wrong.

## Decision

1. **One uv workspace.** The root `pyproject.toml` is not a distribution. Members are `packages/*`. One committed `uv.lock`.
2. **`agentic-datacenter` is a namespace package.** `agentic_datacenter.core`, `.plant`, `.supervisory`, `.net`, `.governance` and `.scenarios` come from six distributions. There is no `agentic-datacenter/__init__.py` anywhere; each distribution owns one sub-package. `agentic_datacenter_remora` and `agentic_datacenter_iec61850` are ordinary top-level packages.
3. **Declared dependencies follow the SDD table exactly.** A distribution depends only on the Agentic Datacenter distributions it may import.
4. **Optional packages are opt-in.** The root depends on the six core distributions. `agentic-datacenter-remora` and `agentic-datacenter-iec61850` are installed through the dependency groups `remora` and `iec61850`.
5. **One forbidden-import contract per distribution**, in the root `pyproject.toml`, plus one that keeps REMORA out of everything except `agentic_datacenter_remora`. The contracts forbid direct imports only: a package may reach a lower layer through one it is allowed to import.

| Contract | Forbids |
| --- | --- |
| Core | Importing any other Agentic Datacenter package |
| Plant | Anything but core |
| Supervisory | Anything but core |
| Net | Plant, governance, scenarios and both optional packages |
| Governance | Plant, net, scenarios and both optional packages |
| Scenarios | Both optional packages |
| REMORA binding | Anything in Agentic Datacenter but governance |
| IEC 61850 | Anything in Agentic Datacenter but core and supervisory |
| REMORA isolation | `remora` and `servers` imported from any package other than `agentic_datacenter_remora` |

## Verification

- `uv run --all-groups lint-imports`: 9 contracts kept.
- With a REMORA import added to `agentic_datacenter.core` and a plant import added to `agentic_datacenter.supervisory`, the two matching contracts were reported broken and the other seven kept. The changes were then removed.
- `uv sync` without groups installs the six core distributions and no REMORA.

## Consequences

- The contracts need every root package to be importable, so the contract check runs with all groups installed. The jobs that test without REMORA or without the IEC 61850 package (`ADC-PIN-001`, `ADC-IEC-005`) need a contract file that leaves those packages out; that is Stage 1 CI work.
- The harness may not import a gate binding. A binding is found through the `agentic_datacenter.gates` entry-point group (SDD 5.3), which is what lets a gate outside this repository be benchmarked unchanged (`ADC-BEN-005`).
- "May import: governance, REMORA" is read strictly for the binding: it may not import `agentic_datacenter.core` or `agentic_datacenter.supervisory` directly. If the binding turns out to need a core type, governance re-exports it or the SDD table is changed.
- Three contracts cannot be written until their code exists and are added in the stage that creates it: plant modules independent of each other (Stage 1), the protocol library confined to `agentic_datacenter_iec61850` (Stage 6), and `agentic_datacenter_remora` limited to `remora.sdk` (Stage 8).
- Cross-package tests live in the top-level `tests/` directory; a package's own tests live inside the package. Neither exists at Stage 0.
