"""CI as code: pinning, per-package jobs, the ruleset and provenance (SDD 12.4)."""

import hashlib
import json
import re
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO / ".github/workflows").glob("*.yml"))
PACKAGES = sorted(p.name for p in (REPO / "packages").iterdir() if p.is_dir())
EXPECTED_WORKFLOWS = {
    "pr", "integration", "nightly", "bench", "bench-runner", "pin-bump", "release",
}  # fmt: skip


def jobs() -> list[tuple[str, str, dict]]:  # type: ignore[type-arg]
    out = []
    for path in WORKFLOWS:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        out += [(path.stem, name, job) for name, job in data["jobs"].items()]
    return out


def test_the_workflows_of_the_design_exist() -> None:
    assert {p.stem for p in WORKFLOWS} == EXPECTED_WORKFLOWS


@pytest.mark.req("ADC-CI-003")
def test_every_third_party_action_is_pinned_by_commit_sha() -> None:
    uses = [
        (path.name, line.split("uses:", 1)[1].split("#")[0].strip())
        for path in WORKFLOWS
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip().startswith(("uses:", "- uses:"))
    ]
    assert uses
    unpinned = [u for u in uses if not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", u[1])]
    assert unpinned == []


#: Jobs on the self-hosted benchmark runner run on the host, because that runner may
#: be Linux, macOS or Windows, where a container is not available. They check
#: nothing about a change; they make result cards (docs/guides/bench-runner.md).
ON_THE_HOST = {("bench-runner", "bench")}


@pytest.mark.req("ADC-CI-003")
def test_every_job_runs_in_the_digest_pinned_reference_image() -> None:
    images = {
        (wf, name, str(job.get("container", "")))
        for wf, name, job in jobs()
        if (wf, name) not in ON_THE_HOST
    }
    assert all(re.search(r"@sha256:[0-9a-f]{64}$", image) for _, _, image in images), images
    assert len({image for _, _, image in images}) == 1, "one reference image for every job"


@pytest.mark.req("ADC-CI-003")
def test_every_install_uses_the_frozen_lock() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in WORKFLOWS)
    installs = re.findall(r"uv sync[^\n]*", text)
    assert installs and all("--frozen" in command for command in installs)


@pytest.mark.req("ADC-CI-003")
def test_workflow_tokens_are_read_only_unless_a_job_says_otherwise() -> None:
    for path in WORKFLOWS:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert data.get("permissions") == {"contents": "read"}, path.name


def test_pull_requests_from_forks_get_no_secrets() -> None:
    text = (REPO / ".github/workflows/pr.yml").read_text(encoding="utf-8")
    assert "pull_request_target" not in text
    assert not re.search(r"\$\{\{\s*secrets\.", text)


def test_no_job_retries_a_failing_test() -> None:
    text = "\n".join(p.read_text(encoding="utf-8") for p in WORKFLOWS)
    assert "--reruns" not in text and "retry" not in text.lower()


@pytest.mark.req("ADC-CI-002")
def test_each_distribution_is_tested_alone_with_only_its_declared_dependencies() -> None:
    job = yaml.safe_load((REPO / ".github/workflows/pr.yml").read_text("utf-8"))["jobs"]["unit"]
    assert sorted(job["strategy"]["matrix"]["package"]) == [
        p for p in PACKAGES if p not in {"agentic-datacenter-remora", "agentic-datacenter-iec61850"}
    ]
    run = "\n".join(step.get("run", "") for step in job["steps"])
    assert "uv sync --frozen --package ${{ matrix.package }}" in run
    assert "--group test" in run


@pytest.mark.req("ADC-PIN-001")
def test_integration_runs_without_remora_and_without_the_iec61850_package() -> None:
    data = yaml.safe_load((REPO / ".github/workflows/integration.yml").read_text("utf-8"))
    assert {"without-remora", "without-iec61850", "cross-architecture"} <= set(data["jobs"])


@pytest.mark.req("ADC-CI-004")
def test_cross_architecture_job_compares_two_architectures() -> None:
    data = yaml.safe_load((REPO / ".github/workflows/integration.yml").read_text("utf-8"))
    runners = data["jobs"]["cross-architecture-run"]["strategy"]["matrix"]["runner"]
    assert len(runners) == 2 and any("arm" in r for r in runners)
    compare = "\n".join(s.get("run", "") for s in data["jobs"]["cross-architecture"]["steps"])
    assert "quantized" in compare


def pin_bump() -> dict:  # type: ignore[type-arg]
    data = yaml.safe_load((REPO / ".github/workflows/pin-bump.yml").read_text("utf-8"))
    assert data[True] == {"pull_request": {"paths": ["REMORA_PIN"]}}
    return data["jobs"]  # type: ignore[no-any-return]


@pytest.mark.req("ADC-PIN-004")
@pytest.mark.parametrize(
    ("changed", "allowed"),
    [
        (["REMORA_PIN", "uv.lock"], True),
        (["REMORA_PIN", "uv.lock", "packages/agentic-datacenter-remora/pyproject.toml"], True),
        (["REMORA_PIN", "uv.lock", "contracts/chw.yaml"], False),
        (["REMORA_PIN", "docs/uv.lock"], False),
        (["REMORA_PIN", "uv.lock", "packages/agentic-datacenter-governance/pyproject.toml"], False),
        (["REMORA_PIN", "uv.lock", ".github/workflows/pin-bump.yml"], False),
    ],
)
def test_a_pin_bump_that_changes_anything_but_the_pin_and_the_lock_fails(
    changed: list[str], allowed: bool
) -> None:
    """Runs the check of the workflow, as written, on a list of changed files."""
    import shutil
    import subprocess

    shell = shutil.which("sh")
    if shell is None:
        pytest.skip("needs a POSIX shell to run the workflow's own command")
    (step,) = [
        s for s in pin_bump()["only-pin-and-lock"]["steps"] if "may change" in s.get("name", "")
    ]
    lines = step["run"].strip().splitlines()
    assert 'git diff --name-only "origin/${{ github.base_ref }}...HEAD"' in lines[0]
    assert lines[-1].startswith('test -z "$(echo "$changed" | grep -v -x ')
    done = subprocess.run(
        [shell, "-c", lines[-1]], env={"changed": "\n".join(changed), "PATH": "/usr/bin:/bin"}
    )
    assert (done.returncode == 0) is allowed


@pytest.mark.req("ADC-PIN-004")
def test_a_pin_bump_carries_the_metric_difference_against_the_previous_pin() -> None:
    job = pin_bump()["metric-difference"]
    runs = [step["run"] for step in job["steps"] if "run" in step]
    old_tree = "build/pin-old-tree"
    # The same benchmark at both pins: the commands differ only in where they run and write.
    matrix = [r for r in runs if "agentic-datacenter bench run" in r]
    assert len(matrix) == 2 and all("--gate remora_governed" in r for r in matrix)
    new, old = (re.search(r"bench run (.*) --out (\S+?)\)?$", r) for r in matrix)
    assert new and old and new.group(1) == old.group(1)
    assert new.group(2) == "build/pin-new" and old.group(2) == "../pin-old"
    assert old_tree not in matrix[0] and matrix[1].startswith(f"(cd {old_tree} && ")
    # The old tree is the base of the pull request, with its own lock and environment,
    # and each tree is checked to hold the REMORA its own pin names.
    (base,) = [r for r in runs if "git worktree add" in r]
    assert f'git worktree add --detach {old_tree} "origin/${{{{ github.base_ref }}}}"' in base
    assert "UV_PROJECT_ENVIRONMENT=.venv uv sync --frozen --all-groups" in base
    assert sum("tools/check_pin.py" in r for r in runs) == 2 and "tools/check_pin.py" in base
    # The difference is made from the two cards and the two pins, fails the job when it
    # blocks the bump, and is on the pull request as the run's summary and an artifact.
    (diff,) = [r for r in runs if "tools/pin_diff.py" in r]
    for argument in (
        "--old-card build/pin-old/result_card.json", f"--old-pin {old_tree}/REMORA_PIN",
        "--new-card build/pin-new/result_card.json", "--new-pin REMORA_PIN",
        "--out build/pin-diff/pin-diff.md",
    ):  # fmt: skip
        assert argument in diff
    assert "|| status=$?" in diff and diff.strip().endswith('exit "$status"')
    assert 'cat build/pin-diff/pin-diff.md >> "${GITHUB_STEP_SUMMARY' in diff
    (upload,) = [s for s in job["steps"] if "upload-artifact" in s.get("uses", "")]
    assert upload["with"]["path"] == "build/pin-diff" and upload["if"] == "always()"
    assert upload["with"]["if-no-files-found"] == "error"


def test_no_job_that_calls_a_paid_model_api_starts_by_itself() -> None:
    data = yaml.safe_load((REPO / ".github/workflows/bench.yml").read_text("utf-8"))
    triggers = data[True] if True in data else data["on"]
    assert set(triggers) <= {"workflow_dispatch", "release"}


@pytest.mark.req("ADC-CI-005")
def test_ruleset_requires_a_pull_request_and_its_checks() -> None:
    ruleset = json.loads((REPO / ".github/rulesets/main.json").read_text(encoding="utf-8"))
    rules = {rule["type"]: rule.get("parameters", {}) for rule in ruleset["rules"]}
    assert ruleset["enforcement"] == "active"
    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert ruleset["bypass_actors"] == []
    assert "pull_request" in rules
    checks = {c["context"] for c in rules["required_status_checks"]["required_status_checks"]}
    pr_jobs = set(yaml.safe_load((REPO / ".github/workflows/pr.yml").read_text("utf-8"))["jobs"])
    assert checks and checks <= pr_jobs
    assert {"static", "traceability", "conformance"} <= checks
    assert "deletion" in rules and "non_fast_forward" in rules


@pytest.mark.req("ADC-CI-005")
def test_review_is_required_from_everyone_but_the_maintainer() -> None:
    """While there is one maintainer, only the admin role may merge without a review.

    The bypass is limited to pull requests, and the required checks are in the
    other ruleset, which nobody bypasses.
    """
    path = REPO / ".github/rulesets/main-review.json"
    ruleset = json.loads(path.read_text(encoding="utf-8"))
    assert ruleset["enforcement"] == "active"
    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    assert ruleset["bypass_actors"] == [
        {"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "pull_request"}
    ]
    (rule,) = ruleset["rules"]
    review = rule["parameters"]
    assert rule["type"] == "pull_request"
    assert review["required_approving_review_count"] >= 1
    assert review["require_code_owner_review"] is True


@pytest.mark.req("ADC-CI-005")
def test_release_tags_must_be_signed() -> None:
    ruleset = json.loads((REPO / ".github/rulesets/tags.json").read_text(encoding="utf-8"))
    assert ruleset["target"] == "tag"
    assert "required_signatures" in {rule["type"] for rule in ruleset["rules"]}


@pytest.mark.req("ADC-CI-005")
def test_benchmark_tags_cannot_be_moved_or_deleted() -> None:
    path = REPO / ".github/rulesets/benchmark-tags.json"
    ruleset = json.loads(path.read_text(encoding="utf-8"))
    assert ruleset["target"] == "tag" and ruleset["enforcement"] == "active"
    assert ruleset["conditions"]["ref_name"]["include"] == ["refs/tags/benchmark-*"]
    assert ruleset["bypass_actors"] == []
    assert {"deletion", "update", "non_fast_forward"} <= {r["type"] for r in ruleset["rules"]}


def test_every_ruleset_file_is_checked() -> None:
    checked = {"main.json", "main-review.json", "tags.json", "benchmark-tags.json"}
    assert {p.name for p in (REPO / ".github/rulesets").glob("*.json")} == checked


@pytest.mark.req("ADC-CI-005")
def test_code_owners_cover_interlocks_network_governance_and_the_design_document() -> None:
    owners = (REPO / ".github/CODEOWNERS").read_text(encoding="utf-8")
    for path in (
        "interlocks.py",
        "packages/agentic-datacenter-net/",
        "packages/agentic-datacenter-governance/",
        "docs/design/SDD-ADC-001.md",
    ):
        assert path in owners


@pytest.mark.req("ADC-DOC-003")
def test_docstrings_are_required_on_every_public_object() -> None:
    lint = tomllib.loads((REPO / "pyproject.toml").read_text("utf-8"))["tool"]["ruff"]["lint"]
    assert "D" in lint["select"]
    for pattern, ignored in lint["per-file-ignores"].items():
        if "D" in ignored:
            assert "tests" in pattern or pattern == "conftest.py", pattern


# --- provenance --------------------------------------------------------------

TERMS = REPO / "tools/forbidden_terms.sha256"
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".json", ".txt", ""}


def hashed_words(text: str) -> set[str]:
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", text.lower())
    grams = set(words) | {" ".join(p) for p in zip(words, words[1:], strict=False)}
    grams |= {" ".join(p) for p in zip(words, words[1:], words[2:], strict=False)}
    return {hashlib.sha256(g.encode("utf-8")).hexdigest() for g in grams}


def test_term_scan_finds_a_hashed_term_of_one_to_three_words() -> None:
    forbidden = hashlib.sha256(b"acme tower project").hexdigest()
    assert forbidden in hashed_words("Built for the ACME Tower Project, phase 2.")
    assert forbidden not in hashed_words("Built for the Acme project tower.")


@pytest.mark.req("ADC-PRV-002")
def test_no_tracked_file_contains_a_forbidden_term() -> None:
    """The terms are committed as hashes only, so the names are not in the repository."""
    import subprocess

    forbidden = {
        line.split()[0]
        for line in TERMS.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }
    tracked = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout.split("\n")
    hits = []
    for name in filter(None, tracked):
        path = REPO / name
        if path.suffix in TEXT_SUFFIXES and path.is_file():
            if forbidden & hashed_words(path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(name)
    assert hits == []


@pytest.mark.req("ADC-PRV-001")
@pytest.mark.req("ADC-PRV-005")
def test_notices_state_the_basis_and_the_standards_and_state_no_reproduction() -> None:
    notices = (REPO / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "informed by how real modular data centers" in notices
    assert "does not identify or quote any particular facility" in notices
    assert "No text from any standard is reproduced" in notices
    assert "No text from any design document is reproduced" in notices
    for standard in ("62443-3-2", "62443-3-3", "EN 15232", "ASHRAE TC 9.9", "ISO 8528-5", "61850"):
        assert standard in notices


def test_every_distribution_carries_the_text_of_its_licence() -> None:
    """A wheel is built from the package directory, so the text has to be in it."""
    root = (REPO / "LICENSE").read_text(encoding="utf-8")
    for name in PACKAGES:
        project = tomllib.loads((REPO / "packages" / name / "pyproject.toml").read_text("utf-8"))
        text = (REPO / "packages" / name / "LICENSE").read_text(encoding="utf-8")
        if name == "agentic-datacenter-iec61850":
            assert project["project"]["license"] == "GPL-3.0-or-later"
            assert "GNU GENERAL PUBLIC LICENSE" in text and "Version 3, 29 June 2007" in text
        else:
            assert project["project"]["license"] == "BUSL-1.1", name
            assert text == root, name


def test_the_benchmark_runner_is_started_by_hand_only() -> None:
    """A self-hosted runner must never run what a pull request brings."""
    data = yaml.safe_load((REPO / ".github/workflows/bench-runner.yml").read_text(encoding="utf-8"))
    assert list(data[True]) == ["workflow_dispatch"]
    assert data["jobs"]["bench"]["runs-on"] == ["self-hosted", "bench"]
    for path in WORKFLOWS:
        if path.name != "bench-runner.yml":
            assert "self-hosted" not in path.read_text(encoding="utf-8"), path.name


def test_no_workflow_pastes_an_input_or_event_text_into_a_shell_script() -> None:
    """GitHub pastes ${{ }} into a script before the shell reads it, so text there runs as code.

    Inputs and event fields are passed as environment variables instead, and
    the benchmark runner checks each before use.
    """
    risky = re.compile(r"\$\{\{\s*(inputs\.|github\.event\.|github\.head_ref)")
    for path in WORKFLOWS:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for job in data.get("jobs", {}).values():
            for step in job.get("steps", []):
                assert not risky.search(str(step.get("run", ""))), (path.name, step.get("name"))
    runner = (REPO / ".github/workflows/bench-runner.yml").read_text(encoding="utf-8")
    assert "Check the inputs" in runner
