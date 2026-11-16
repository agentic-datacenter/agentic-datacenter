# Stage 0 review sheet

Stage 0 exits when its deliverables are reviewed and the open questions in section 14 of the design document are "answered or deferred in writing". This sheet is where that is written. The **Owner decision** column is empty on purpose: it is filled in by the reviewer, in the Stage 0 PR.

## 1. Deliverables

| Deliverable (SDD 13, Stage 0) | Where | State |
| --- | --- | --- |
| The design document | `docs/design/SDD-ADC-001.md` | Present |
| Zone model | `docs/design/zone_model.md` | Written; 6 open points |
| Threat model | `docs/design/threat_model.md` | Written |
| REMORA binding from interface discovery | `docs/design/remora_binding.md` | Written; 3 differences, 1 unconfirmed statement |
| ADR: module system | `docs/design/adr/0001-module-system.md` | Proposed |
| ADR: first REMORA pin | `docs/design/adr/0002-remora-pin.md` | Proposed |
| ADR: library choices | `docs/design/adr/0003-library-choices.md` | Proposed |
| ADR: GPLv3 position (SDD 8.5) | `docs/design/adr/0004-licence-position.md` | Decided 2026-11-12: BUSL-1.1; `agentic-datacenter-iec61850` GPL-3.0-or-later |
| Empty uv workspace with import-linter contracts | `pyproject.toml`, `packages/`, `uv.lock`; ADR 0005 | 9 contracts kept |
| `THIRD_PARTY_NOTICES.md` | Repository root | Written |

Provenance requirements closed by Stage 0:

| ID | How it is met now | What still enforces it later |
| --- | --- | --- |
| `ADC-PRV-001` | Nothing written in this stage quotes the reference specification; behaviour is described in original words | Review |
| `ADC-PRV-002` | The source is referred to only as "the reference specification" | Hashed forbidden-term scan in CI, Stage 1. The list of terms has to come from the owner; it is not known to the build |
| `ADC-PRV-003` | The restricted profile is in `.gitignore`. No profile exists yet | `generic_dc.yaml` in Stage 1 |
| `ADC-PRV-004` | No profile exists yet | Schema check in CI, Stage 1 |
| `ADC-PRV-005` | `THIRD_PARTY_NOTICES.md` lists the reference specification and every standard cited, with the no-reproduction statement | Updated per PR |

## 2. Open questions from section 14

"Proposed" is the build's suggestion only.

| # | Question | Proposed disposition | Blocks | Owner decision |
| --- | --- | --- | --- | --- |
| 1 | `remora build-toolspec` in a later pin | Defer. Tracked as the Stage 8 entry condition; nothing earlier depends on it. Milestone M1 runs under `DECISION_ONLY` without it | Stage 8 | |
| 2 | Whether values derived from the reference specification may appear in a public repository | Defer while the repository is private. Must be answered before any change of visibility | Publication | |
| 3 | Which agent runtime drives the demonstration first; whether a second harness is in scope for v1 | Defer to Milestone M1. The two scripted agents need no runtime, and they carry the core result | `llm_agent` runs | |
| 4 | Licence position for the GPLv3 protocol library | Decide in ADR 0004 before Stage 6. Does not block Stages 1 to 5 | Stage 6 | Decided 2026-11-12: option A, see ADR 0004 |
| 5 | Whether the demo needs an operator-facing HMI beyond the read-only dashboard | Defer to Stage 9. Version 1 states no operator actions from the dashboard | Stage 9 | |
| 6 | Access to licensed copies of IEC 62443-3-2 and 3-3 | Needed before Stage 6 closes, to check requirement-enhancement numbers and security levels (SDD 4.4). Until then the matrix carries a "not verified against the standard text" note | Stage 6 exit | |

## 3. Proposed changes to the design document

The design document is changed first, by PR. None of these has been applied; each is described where it was found.

| # | Section | Change | Detail |
| --- | --- | --- | --- |
| 1 | 5.2 | The binding needs REMORA's `sdk` extra as well as `security` | `remora_binding.md` 3.1. Already reflected in `packages/agentic-datacenter-remora/pyproject.toml`, because the governed client cannot be imported otherwise |
| 2 | 9.2 | Two execute calls: `execute_accepted()` for ACCEPT, `execute()` after approval; an asynchronous result is treated as unknown | `remora_binding.md` 3.2 |
| 3 | 11, `ADC-PIN-006` | The three maturity words named are not the register's vocabulary at the pin | `remora_binding.md` 3.3 |
| 4 | 9.2 | "Register lists rollback as PARTIAL" could not be confirmed | `remora_binding.md` 3.4 |
| 5 | 4.2, 8.3 | The data collector's Modbus polling has no conduit | `zone_model.md`, open point 1 |
| 6 | 4.2 | State the initiator of `C3`, and the single destination of `C5` | `zone_model.md`, open points 2 and 3 |
| 7 | 4.2, 7.5 | Time relay and alarm notification have no conduit | `zone_model.md`, open points 4 and 5 |
| 8 | 4.1, 8.2 | Zone of the electrical room units; devices of `Z1-BLDG` | `zone_model.md`, open point 6 |
| 9 | 2, 5.4, 14 | `ADC-PRV-003` and the repository layout say the restricted profile is git-ignored; section 14 said derived values were committed. Since resolved: none is committed. One sentence in 14 would remove the doubt | This sheet |

## 4. Questions for the REMORA maintainer

From `remora_binding.md`, sections 4 and 5. None blocks Stage 1.

1. Can the governed path take its time from a host-supplied clock, so that `SHADOW` and `GOVERNED` runs and scenario `AD-09` are reproducible in `inproc` mode?
2. Which register and field should a host quote for capability maturity, and where is rollback recorded?
3. What is the supported way to run the control plane in-process behind `RemoraClient`?

## 5. Things the reviewer should know that are not in the design document

- **The repository had no licence file at Stage 0.** It carries BUSL-1.1 since 2026-11-12; see ADR 0004.
- **No CI exists yet.** The design document places the CI pipeline in Stage 1. The checks in `CONTRIBUTING.md` were run by hand for this stage and pass.
- **Engineering review.** Sections 3, 6 and 7 are to be reviewed by a practising data center or controls engineer before a public result (SDD 6.7). That review has not happened and is not a Stage 0 exit condition.
- **The list of forbidden terms for `ADC-PRV-002`** must be supplied by the owner as hashes before the Stage 1 scan can be written.
