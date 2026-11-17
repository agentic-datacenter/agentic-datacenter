# Contributing

These rules apply to human and automated contributors alike. Agentic-Datacenter was built from one design document, `docs/design/SDD-ADC-001.md`; decisions made since are ADRs in `docs/design/adr/`. The opening table of the design document says which sections matter for your change. If the design document is ambiguous or wrong, say so in the pull request instead of guessing.

## Setup and checks

Requires [uv](https://docs.astral.sh/uv/). Python 3.12 is selected by `.python-version` and fetched by `uv` if missing.

```sh
uv sync                 # eight of the ten packages and the tools, without REMORA and the IEC 61850 server
uv sync --all-groups    # adds agentic-datacenter-remora and agentic-datacenter-iec61850 (Linux wheels only)
```

Run these before opening a pull request, with all groups installed. They are what the `static` and `docs` jobs of `.github/workflows/pr.yml` run, and then the whole suite:

```sh
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run python tools/core_contracts.py build/importlinter-core.toml && uv run lint-imports --config build/importlinter-core.toml
uv run agentic-datacenter modules lock --check
uv run agentic-datacenter profile schema --check
uv run python tools/gen_reference.py --check
uv run mkdocs build --strict
uv run pytest -n auto --dist loadfile     # about 8 minutes on eight cores, against about 45 in one process
```

For a small change, run the tests that touch what changed first. `uv run python tools/ci_local.py` runs the `pr` workflow on your machine, job by job: `--list` shows what would run, and `--job static --docker` runs one job in the reference image (ADR 0011). `git config core.hooksPath .githooks` runs the static job before every push.

## Every pull request

- Names the requirement IDs it closes in its description.
- Is test-first: failing tests are committed before the implementation.
- Stays under about 1,500 changed lines, not counting generated maps and fixtures. Split it if it is larger.
- Is merged by a person. Nobody merges their own PR, and nothing merges automatically.
- Adds no dependency beyond those in section 5 of the design document without an ADR.
- Carries no authorship or co-author trailer naming an AI tool, in commits or in files.

## Things that are never done here

- Copying text from a design document of a real facility or from any standard into the repository.
- Writing anything that identifies a real facility: the names of a project, owner, engineer or site, or the title, issue, date or section numbers of a design document, anywhere, including test names and commit messages.
- Committing `profiles/restricted_ref.yaml`, or any value taken from a real facility.
- Changing REMORA from an Agentic-Datacenter pull request. Changes REMORA needs go as separate PRs against its `dev` branch.
- Importing REMORA outside `agentic-datacenter-remora`, or the IEC 61850 protocol library outside `agentic-datacenter-iec61850`.
- Connecting to real equipment, or binding a protocol server to a reachable interface.

## Documents that travel with code

| When you add | You also add, in the same PR |
| --- | --- |
| A plant module | Its module spec under `docs/design/modules/`, its manifest and its stub |
| A decision that is not in the design document | An ADR in `docs/design/adr/`, with a status |
| A dependency or a source | An entry in `THIRD_PARTY_NOTICES.md` |
| A profile value | Its `source` or `assumed` field |
| A test for a requirement | The marker `@pytest.mark.req("ADC-XXX-NNN")` |

A pin bump is its own PR. It changes only `REMORA_PIN` and `uv.lock`, names the new tag, and attaches the scenario-matrix metric difference against the previous pin. The `pin-bump` workflow checks the first and makes the second: `uv run python tools/ci_local.py --workflow pin-bump --base main` runs it on your machine and leaves the difference in `build/pin-diff/pin-diff.md`. The one time it was run, on a replay of the last bump, it took 23 minutes.

## Gates from other projects

A gate from another project is not added to this repository. It is loaded through its own `agentic_datacenter.gates` entry point or served over HTTP to the `http_gate` binding; see `docs/guides/bring-your-own-gate.md`. Changes to Agentic-Datacenter that a gate author needs are welcome as issues or pull requests like any other. A result is shared through the "Gate result" issue form, not by pull request.
