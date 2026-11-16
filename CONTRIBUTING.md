# Contributing

Agentic Datacenter is built from one design document, in fixed stages, by small pull requests that a person merges. These rules apply to human and automated contributors alike. They restate section 13 of `docs/design/SDD-ADC-001.md`; if the two differ, the design document wins.

## Before you write anything

- Read the design document and the ADRs in `docs/design/adr/`. Its opening table says which sections matter for your role.
- Work on the current stage only. A stage does not start until the exit criterion of the previous one is met.
- If the design document is ambiguous or wrong, stop. Propose the change to the design document in the same PR instead of guessing.

## Every pull request

- Names the requirement IDs it closes in its description.
- Is spec-first and test-first: failing tests are committed before the implementation.
- Stays under about 1,500 changed lines, not counting generated maps and fixtures. Split it if it is larger.
- Is merged by a person. Nobody merges their own PR, and nothing merges automatically.
- Adds no dependency beyond those in section 5 of the design document without an ADR.
- Carries no authorship or co-author trailer naming an AI tool, in commits or in files.

## Things that are never done here

- Copying text from the reference specification or from any standard into the repository.
- Writing anything that identifies the reference specification: the names of its project, owner, engineer or site, its title, issue, date or section numbers, anywhere, including test names and commit messages.
- Committing `profiles/restricted_ref.yaml`, or any value taken from the reference specification.
- Changing REMORA from a Agentic Datacenter pull request. Changes REMORA needs go as separate PRs against its `dev` branch.
- Importing REMORA outside `agentic-datacenter-remora`, or the IEC 61850 protocol library outside `agentic-datacenter-iec61850`.
- Connecting to real equipment, or binding a protocol server to a reachable interface.

## Gates from other projects

A gate from another project is not added to this repository. It is loaded through its own `agentic_datacenter.gates` entry point or served over HTTP to the `http_gate` binding; see `docs/guides/bring-your-own-gate.md`. Changes to Agentic Datacenter that a gate author needs, such as a field the gate interface lacks or a scenario that would test something new, are welcome as issues or pull requests like any other. A result is shared through the "Gate result" issue form, not by pull request.

## Local setup

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is selected by `.python-version` and fetched by `uv` if missing.

```sh
uv sync                 # the six core packages, the optional measured-input package and the tools, without REMORA
uv sync --all-groups    # adds agentic-datacenter-remora and agentic-datacenter-iec61850; needs read access to the REMORA repository
```

## Checks

Run these before opening a pull request. They become required CI jobs in Stage 1.

```sh
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run --all-groups mypy
uv run --all-groups lint-imports
```

## Documents that travel with code

| When you add | You also add, in the same PR |
| --- | --- |
| A plant module | Its module spec under `docs/design/modules/`, its manifest and its stub |
| A decision that is not in the design document | An ADR in `docs/design/adr/`, with a status |
| A dependency or a source | An entry in `THIRD_PARTY_NOTICES.md` |
| A profile value | Its `source` or `assumed` field |
| A test for a requirement | The marker `@pytest.mark.req("ADC-XXX-NNN")` |

## Changing the REMORA pin

A pin bump is its own PR. It changes only `REMORA_PIN` and `uv.lock`, names the new tag, and from Stage 8 onward attaches the scenario-matrix metric difference against the previous pin.

## Running the checks

Hosted runners are not available to this repository (ADR 0011). The workflows in `.github/workflows/` are run locally:

```sh
uv run python tools/ci_local.py --list                 # what would run
uv run python tools/ci_local.py                        # the whole pr workflow, on the host
uv run python tools/ci_local.py --job static --docker  # one job in the reference image
uv run python tools/ci_local.py --publish              # also report commit statuses (clean, pushed commit only)
git config core.hooksPath .githooks                    # static checks before every push
```
