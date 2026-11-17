# ADR 0011: The workflows are run locally and reported as commit statuses

- **Status:** Accepted. Decided with the owner on 2026-11-12.
- **Date:** 2026-11-12
- **SDD:** 12.4; requirements `ADC-CI-001` to `-004`

## Context

The design document places every check in GitHub Actions. The account this repository belongs to has no Actions minutes, so no workflow has ever run here. Until now the checks were run by hand and described in each pull request, which leaves nothing on the commit that a reviewer or a ruleset can read.

The workflow files are still the best statement of what must pass: they are reviewed, they are covered by conformance tests, and they name the digest-pinned image the results are defined on.

## Decision

1. **The workflow files stay the definition.** `tools/ci_local.py` reads a workflow and runs the commands of its jobs on the developer's machine. It keeps no list of its own, and a conformance test checks that its plan has every job and every command of the workflow.
2. **Two places to run.** On the host, each job gets its own virtual environment under `build/ci/`, so a job that installs one distribution alone does not disturb the working environment. With `--docker`, each job runs in the image the workflow names, from a clean clone of the commit. The image run is the one that counts for `ADC-KRN-001` (bit for bit on the reference image).
3. **Results go to GitHub as commit statuses**, one per job, under the job's name. Those are the names the branch ruleset already requires, so the ruleset needs no change. Commit statuses are part of the repository API and use no Actions minutes.
4. **A status is published only for a pushed commit with a clean working tree.** Otherwise it would describe something GitHub does not have.
5. **A pre-push hook runs the static job.** It is opt-in: `git config core.hooksPath .githooks`.

## Consequences

- A status says where it was run (host or reference image) and by whom it was posted is whoever holds the token. This is weaker than a hosted runner: the person who wrote the change can also post the status. It is an honest record, not an independent one. A self-hosted runner on a second machine would restore the separation and can use the same workflow files unchanged.
- The nightly, integration and benchmark workflows are run the same way, by hand or from a scheduler on a machine the owner chooses. Nothing runs by itself today.
- Jobs that need the private REMORA repository run on the host, where credentials exist; the reference image has none.
- If Actions becomes available again, nothing has to be undone.

## Addendum 2026-11-13: workflow triggers disabled on GitHub

GitHub kept starting the workflows on every push, and each job was refused before it ran for lack of Actions minutes. The refused jobs carry the same names as the statuses `tools/ci_local.py` publishes, so a pull request with all local statuses green still showed red checks. The six workflows are disabled on GitHub (`gh workflow disable`); the files stay, and `tools/ci_local.py` reads them as before. `gh workflow enable <name>` turns one back on when hosted runners are available again.

## Addendum 2026-11-17: what changes when the repository is public

- **Actions minutes.** The decision rests on the account having no Actions minutes. GitHub does not meter standard hosted runners on public repositories, so that reason is expected to fall away once this repository is public. Nothing has been switched back on in expectation of it. Whether the hosted workflows are enabled again, and whether the commit statuses from `tools/ci_local.py` are kept beside them, is the owner's decision. `tools/ci_local.py` works either way.
- **REMORA.** REMORA-research is a public repository. A job that installs it needs no credentials, on the host or in the reference image.
- **A seventh workflow** was added after this record: `bench-runner`, started by hand, on a self-hosted machine. On a public repository such a machine needs the settings in `docs/guides/bench-runner.md`.
