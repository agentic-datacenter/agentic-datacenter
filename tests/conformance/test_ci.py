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
EXPECTED_WORKFLOWS = {"pr", "integration", "nightly", "bench", "pin-bump", "release"}


def jobs() -> list[tuple[str, str, dict]]:  # type: ignore[type-arg]
    out = []
    for path in WORKFLOWS:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        out += [(path.stem, name, job) for name, job in data["jobs"].items()]
    return out


def test_the_six_workflows_of_the_design_exist() -> None:
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


@pytest.mark.req("ADC-CI-003")
def test_every_job_runs_in_the_digest_pinned_reference_image() -> None:
    images = {(wf, name, str(job.get("container", ""))) for wf, name, job in jobs()}
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


def test_no_job_that_calls_a_paid_model_api_starts_by_itself() -> None:
    data = yaml.safe_load((REPO / ".github/workflows/bench.yml").read_text("utf-8"))
    triggers = data[True] if True in data else data["on"]
    assert set(triggers) <= {"workflow_dispatch", "release"}


@pytest.mark.req("ADC-CI-005")
def test_ruleset_requires_checks_review_and_no_automatic_merge() -> None:
    ruleset = json.loads((REPO / ".github/rulesets/main.json").read_text(encoding="utf-8"))
    rules = {rule["type"]: rule.get("parameters", {}) for rule in ruleset["rules"]}
    assert ruleset["enforcement"] == "active"
    assert ruleset["conditions"]["ref_name"]["include"] == ["~DEFAULT_BRANCH"]
    review = rules["pull_request"]
    assert review["required_approving_review_count"] >= 1
    assert review["require_code_owner_review"] is True
    checks = {c["context"] for c in rules["required_status_checks"]["required_status_checks"]}
    pr_jobs = set(yaml.safe_load((REPO / ".github/workflows/pr.yml").read_text("utf-8"))["jobs"])
    assert checks and checks <= pr_jobs
    assert {"static", "traceability", "conformance"} <= checks
    assert "deletion" in rules and "non_fast_forward" in rules


@pytest.mark.req("ADC-CI-005")
def test_release_tags_must_be_signed() -> None:
    ruleset = json.loads((REPO / ".github/rulesets/tags.json").read_text(encoding="utf-8"))
    assert ruleset["target"] == "tag"
    assert "required_signatures" in {rule["type"] for rule in ruleset["rules"]}


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
def test_notices_list_the_reference_and_the_standards_and_state_no_reproduction() -> None:
    notices = (REPO / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "The reference specification" in notices and "unpublished" in notices.lower()
    assert "No text from any standard is reproduced" in notices
    assert "No text from it is reproduced" in notices
    for standard in ("62443-3-2", "62443-3-3", "EN 15232", "ASHRAE TC 9.9", "ISO 8528-5", "61850"):
        assert standard in notices
