# ADR 0003: Language, tooling and library choices

- **Status:** Accepted.
- **Date:** 2026-11-12
- **SDD:** 5 ("Technology choices"), 8.5, 13 ("Do not add dependencies beyond section 5 without an ADR")

## Context

The SDD names the technology for each concern and asks Stage 0 to record the choices. Some are fixed now because the workspace needs them; others are named but must not be pinned until the stage that first uses them, so the version is chosen against what is current then.

## Decision

### Fixed at Stage 0 (in the workspace and the lock)

| Concern | Choice | Note |
| --- | --- | --- |
| Language | Python 3.12 | `requires-python = ">=3.12"`; `.python-version` selects 3.12 for development and CI |
| Workspace and lock | `uv` workspace, `uv.lock` committed | One lock for all eight distributions |
| Build backend | `hatchling` | Same backend as REMORA; handles the shared `agentic-datacenter` namespace with an explicit package list |
| Lint and format | `ruff` | Rule sets E, F, W, I, B, UP, D with Google-style docstrings; Markdown is excluded from formatting |
| Types | `mypy --strict` | Namespace packages with explicit package bases |
| Tests | `pytest`, `hypothesis` | Marker `req` registered for requirement traceability (`ADC-CI-001`) |
| Boundaries | `import-linter` | See ADR 0005 |

### Named now, pinned in the stage that first uses them

| Concern | Choice | Pinned in |
| --- | --- | --- |
| Schemas | `pydantic` v2; YAML for profiles and contracts; JSON Schema exported | Stage 1 |
| Historian | SQLite for metadata, Parquet for time series | Stage 5 |
| Operator and agent API | `FastAPI` over mutual TLS | Stage 5 |
| Modbus/TCP | `pymodbus` | Stage 6, after checking the current major version |
| BACnet/IP | `bacpypes3` | Stage 6 |
| OPC UA | `asyncua` | Stage 6 |
| SNMP | `pysnmp` or a maintained successor | Stage 6, in its own ADR, because maintenance status has changed over time |
| IEC 61850 MMS | `libiec61850` through Python bindings, inside `agentic-datacenter-iec61850` only | Stage 6, and only after ADR 0004 is decided |
| Reference tools for `F2` validation | For example pandapower, EnergyPlus or the Modelica Buildings library | By ADR when the first `F2` comparison is written; validation job only, never at run time |

## Consequences

- No protocol, schema or web library is installed at Stage 0. The lock contains only the tooling above and, in the `remora` group, REMORA with its two extras.
- Any library not in these tables needs a new ADR before it is added.
- The lint rule set is a starting point. The lint rule that forbids wall-clock and unseeded random access (`ADC-KRN-003`) is added in Stage 1 with the kernel.
- Development tools are not version-constrained in `pyproject.toml`; the committed lock is what fixes them.
