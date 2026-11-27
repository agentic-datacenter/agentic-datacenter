# Contributing

These rules apply to human and automated contributors alike, and so does the [code of conduct](CODE_OF_CONDUCT.md). Agentic-Datacenter was built from one design document, `docs/design/SDD-ADC-001.md`; decisions made since are ADRs in `docs/design/adr/`. The opening table of the design document says which sections matter for your change. If the design document is ambiguous or wrong, say so in the pull request instead of guessing.

## The easy ways to contribute

Most of what this project needs from others takes no pull request, no setup and no grant of rights.

| You want to | Do this | What it asks of you |
| --- | --- | --- |
| Say what should be tested | [Propose a scenario](docs/guides/propose-a-scenario.md), in words | Two paragraphs |
| Take part with a system of your own | [Register](https://github.com/agentic-datacenter/agentic-datacenter/issues/new?template=gate-registration.yml) | Three fields; your code stays where it is |
| Share a result | The "Gate result" form | The card your run wrote |
| Report something that does not work, or is unclear | The "Problem or question" form | What you ran and what you saw |
| Add a country's grid connection requirements, or correct or complete one | [The grid form](https://github.com/agentic-datacenter/agentic-datacenter/issues/new?template=grid-requirements.yml), in words | The document you read, and its numbers |
| Offer measured data from a plant | [Contribute data](docs/calibration/contribute-data.md), privately | An e-mail |

Four kinds of file can be sent as a pull request without the rules below for code: a scenario file (CC-BY-4.0, your name in its header), an equipment entry (CC-BY-4.0, ADR 0034), a grid requirements file (CC-BY-4.0, your name in its header, [how to write one](docs/guides/grid-requirements.md#write-the-file-yourself)) and a correction to a page of documentation. The checks still run on them.

Everything from here on is for a change to the simulator's own code.

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

## The adoption phase: no new features for now

From 2026-11-25, the project works on what someone new needs to get value from it without help, not on new features. These are taken:

- fixes, and anything a review finds;
- what makes the first run, the first gate and the first facility quicker and clearer;
- reports, templates and checks of contributions;
- documentation by role.

A new feature waits. The owner lifted the freeze once, on 2026-11-25, for the language-model agent (ADR 0035), so that it can be used at launch. The first feature after this phase is an agent of your own, served like a gate. The phase ends when a person from outside the project has reached a result on their own, and has said so in an issue.

## Every pull request

- Names the requirement IDs it closes in its description.
- Is test-first: failing tests are committed before the implementation.
- Stays under about 1,500 changed lines, not counting generated maps and fixtures. Split it if it is larger.
- Is merged by a person, after the required checks have passed. Nothing merges automatically. A pull request from anyone else is reviewed and approved by the maintainer before it is merged. There is one maintainer today, so the maintainer's own pull requests are merged without a second review, once the required checks pass (`.github/rulesets/`).
- Adds no dependency beyond those in section 5 of the design document without an ADR.
- Carries no authorship or co-author trailer naming an AI tool, in commits or in files (`tests/conformance/test_authorship.py`).

## Things that are never done here

- Copying text from the reference specification or from any standard into the repository.
- Writing anything that identifies the reference specification: the names of its project, owner, engineer or site, its title, issue, date or section numbers, anywhere, including test names and commit messages.
- Committing `profiles/restricted_ref.yaml`, or any value taken from the reference specification.
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

## Release tags

A release is a tag `v*` with an SSH signature, made by the maintainer. The `release` workflow verifies the signature before it installs, tests or builds anything, and fails when it does not verify.

- The public keys that may sign a release are in `.github/release-signers/allowed_signers`, one per line, as the first lines of that file describe. The workflow reads the file from the main branch, not from the tagged commit, so a change of keys goes through a pull request like any other change. While the file lists no key, every release fails with a message that says so.
- Sign with that key: `git config gpg.format ssh`, `git config user.signingkey ~/.ssh/<name>.pub`, then `git tag -s v1.2.3 -m "v1.2.3"`. Add the same key to your GitHub account as a signing key, because the ruleset `.github/rulesets/tags.json` asks GitHub for a verified signature too.
- Check a tag before you push it: `uv run python tools/verify_release_tag.py v1.2.3 --signers-ref origin/main`.

The workflow file of a release is the one in the tagged commit. The check therefore stops a tag that is unsigned or signed with another key. It does not stop someone who may push tags and changes the workflow itself; the rulesets and the review of `.github/` are what stand against that.

## Gates from other projects

A gate from another project is not added to this repository. It is loaded through its own `agentic_datacenter.gates` entry point or served over HTTP to the `http_gate` binding; see `docs/guides/bring-your-own-gate.md`. Changes to Agentic-Datacenter that a gate author needs are welcome as issues or pull requests like any other. A result is shared through the "Gate result" issue form, not by pull request.

## Licence of contributions

An equipment entry a maker submits for `equipment/` is under CC-BY-4.0 (ADR 0034), with the attribution its source names. The terms below do not apply to it. The same holds for a scenario file someone outside this project proposes for the library: it is under CC-BY-4.0, with its proposer named in the file's header (ADR 0042).


Agentic-Datacenter is under the Business Source License 1.1 (`LICENSE`), and the Licensor also issues separate commercial licences, through the representative named in `COMMERCIAL_LICENSING.md`. `packages/agentic-datacenter-iec61850` is GPL-3.0-or-later. So that this stays possible, a contribution from anyone other than the Licensor is merged only after its author has agreed to the following, in words, in the pull request:

- You wrote the contribution or have the right to submit it, and it contains no third-party material that the pull request does not name.
- You keep the copyright in your contribution.
- You grant the Licensor named in `LICENSE` a perpetual, worldwide, non-exclusive, royalty-free and irrevocable licence to use, copy, modify and distribute your contribution, and to license it to others under any terms. Those terms include the Business Source License 1.1 and its Change License, GPL-3.0-or-later for `packages/agentic-datacenter-iec61850`, and commercial licences.

A `Signed-off-by` line alone does not grant this.

These terms apply only to a change you ask to have merged into this repository. A gate kept in a repository of your own is not a contribution, whether you wrote it from nothing or started from `examples/`, which is under the MIT licence. Nor is opening an issue, registering a gate, or sharing a result through the "Gate result" form.

## How the code is written

The maintainer writes Agentic-Datacenter with the help of AI coding assistants. Every change is read and merged by the maintainer, is committed under the maintainer's name, and has to pass the same tests and release check as any other. A result counts because the checks pass and anyone can run them again, not because of who or what wrote the code.
