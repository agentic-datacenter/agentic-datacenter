# ADR 0007: Stage-aware traceability, and the tools CI adds

- **Status:** Accepted with the Stage 1 CI PR.
- **Date:** 2026-11-12
- **SDD:** 12.4; requirements `ADC-CI-001` to `-005`, `ADC-DOC-001`, `ADC-DOC-003`

## Context

`ADC-CI-001` says every requirement ID has at least one passing marked test, and that unknown or unclaimed IDs fail the build. Read literally, the build is red from Stage 1 until Stage 9, because most requirements belong to stages that have not started. A check that is always red checks nothing.

The CI design also needs three tools that section 5 of the design document does not name.

## Decision

1. **Traceability follows the staged plan.** `[tool.agentic-datacenter] stage` in the root `pyproject.toml` records the stage the repository has reached. `tools/traceability.py` reads the stage of each requirement from the table in section 13 and requires, for every requirement at or below the current stage: at least one passing test marked with it, no failing test, and a claim by a module manifest or a package. Requirements of later stages are reported as open. A test that cites an ID the design document does not define always fails the build, at any stage.
2. **Raising the stage is a reviewed change.** The stage number changes in the PR that closes a stage, so the diff shows which requirements became mandatory.
3. **Nightly-only tests count, and are labelled.** A requirement whose only tests run nightly (`ADC-KRN-004`) is reported as "verified only by tests not selected in this run", not as a failure.
4. **Docstring coverage is enforced by the linter.** `ADC-DOC-003` asks for 95 %. The ruff pydocstyle rules already require a docstring on every public module, class and function in `packages/*/src` and `tools`, which is 100 %, so no coverage tool is added.
5. **Three tools are added, each in its own dependency group** so nothing but the job that needs it installs it: `mkdocs` (group `docs`) for the strict site build, `pip-audit` (group `audit`) for the vulnerability audit, and a `test` group (`pytest`, `hypothesis`) in every distribution so it can be tested with only its declared dependencies (`ADC-CI-002`).
6. **Pull-request jobs check the import contracts without the REMORA binding.** The full set needs read access to the REMORA repository, which a pull request from a fork must not have. `tools/core_contracts.py` derives the reduced set from the one in `pyproject.toml`; the integration workflow checks the full set with a read token.

## Consequences

- The build can be green at every stage and still fail the moment a due requirement loses its test.
- `ADC-PRV-002` is enforced by a scan against hashed terms. The committed list is empty until the owner supplies the hashes, so until then the scan proves nothing; `tools/forbidden_terms.sha256` says so.
- `ADC-CI-005`: the rulesets under `.github/rulesets/` are the committed definition, and a test checks their content. Applying them to the repository, and comparing the live settings with the files, needs an administrator token and is not done by any job yet.
- The reference image is `ghcr.io/astral-sh/uv` for Python 3.12, pinned by digest. It has no `git`, which several tests need, so each job installs it from the distribution's package index. That one step is not pinned.
- The integration job that installs REMORA needs a repository secret, `REMORA_READ_TOKEN`, with read access to the REMORA repository.
- Workflows have not run on GitHub yet when this ADR is written; they were checked locally by running the same commands outside the container.
