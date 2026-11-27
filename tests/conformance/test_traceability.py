"""ADC-CI-001: every requirement that should be closed has a passing, marked test."""

import importlib.util
import tomllib
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, REPO / "tools" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


trace = load("traceability")
SDD = (REPO / trace.SDD).read_text(encoding="utf-8")
KNOWN = trace.sdd_requirements(SDD)
STAGES = trace.stage_requirements(SDD)
STAGE = int(
    tomllib.loads((REPO / "pyproject.toml").read_text("utf-8"))["tool"]["agentic-datacenter"][
        "stage"
    ]
)


def test_design_document_defines_the_requirement_families() -> None:
    assert {"ADC-SAF-001", "ADC-KRN-004", "ADC-PRV-005", "ADC-BEN-005"} <= KNOWN
    assert len(KNOWN) == len(set().union(*STAGES.values())), "every requirement has a stage"


def test_stage_table_is_read_from_section_13() -> None:
    assert STAGES[0] == {f"ADC-PRV-00{n}" for n in range(1, 6)}
    assert {
        "ADC-SAF-001",
        "ADC-KRN-004",
        "ADC-MOD-005",
        "ADC-CI-005",
        "ADC-DOC-003",
    } <= STAGES[1]
    assert STAGES[2] == {
        "ADC-PRC-001", "ADC-PRC-003", "ADC-CTL-001", "ADC-CTL-002", "ADC-IEC-004",
    }  # fmt: skip
    assert STAGES[7] == set()
    assert set().union(*STAGES.values()) <= KNOWN


def run(report: dict[str, dict[str, list[str]]], claimed: dict[str, set[str]]) -> list[str]:
    stages = {0: {"ADC-PRV-001"}, 1: {"ADC-KRN-001"}, 2: {"ADC-PRC-001"}}
    known = {"ADC-PRV-001", "ADC-KRN-001", "ADC-PRC-001"}
    problems, _ = trace.check(known, stages, 1, report, claimed)
    return list(problems)


GOOD = {"ADC-PRV-001": {"passed": ["t1"]}, "ADC-KRN-001": {"passed": ["t2"]}}
CLAIMS = {"ADC-PRV-001": {"root"}, "ADC-KRN-001": {"agentic-datacenter-core"}}


@pytest.mark.req("ADC-CI-001")
def test_run_with_every_due_requirement_passing_and_claimed_is_clean() -> None:
    assert run(GOOD, CLAIMS) == []


@pytest.mark.req("ADC-CI-001")
def test_requirement_of_a_later_stage_is_open_not_failing() -> None:
    assert not any("PRC-001" in p for p in run(GOOD, CLAIMS))


@pytest.mark.req("ADC-CI-001")
@pytest.mark.parametrize(
    ("report", "claimed", "expected"),
    [
        ({"ADC-PRV-001": {"passed": ["t1"]}}, CLAIMS, "ADC-KRN-001: no passing test"),
        ({**GOOD, "ADC-KRN-001": {"passed": ["a"], "failed": ["b"]}}, CLAIMS, "failing test"),
        ({**GOOD, "ADC-XXX-999": {"passed": ["t"]}}, CLAIMS, "ADC-XXX-999: cited by a test"),
        (GOOD, {"ADC-PRV-001": {"root"}}, "ADC-KRN-001: not claimed"),
        (GOOD, {**CLAIMS, "ADC-ZZZ-001": {"x"}}, "ADC-ZZZ-001: claimed"),
        ({**GOOD, "ADC-PRC-001": {"failed": ["t"]}}, CLAIMS, "ADC-PRC-001: failing"),
    ],
)
def test_each_kind_of_gap_is_reported(
    report: dict[str, dict[str, list[str]]], claimed: dict[str, set[str]], expected: str
) -> None:
    assert any(expected in p for p in run(report, claimed))


@pytest.mark.req("ADC-CI-001")
def test_requirement_verified_only_nightly_is_a_note_not_a_failure() -> None:
    report = {**GOOD, "ADC-KRN-001": {"deselected": ["t"]}}
    assert run(report, CLAIMS) == []


@pytest.mark.req("ADC-CI-001")
def test_a_requirement_another_run_verifies_is_a_note_only_when_named_and_only_when_skipped() -> (
    None
):
    """The keyed term scan is skipped on a pull request, which is given no key."""
    stages = {0: {"ADC-PRV-001"}, 1: {"ADC-KRN-001"}}
    known = {"ADC-PRV-001", "ADC-KRN-001"}
    skipped = {**GOOD, "ADC-KRN-001": {"skipped": ["t"]}}
    named = frozenset({"ADC-KRN-001"})
    assert trace.check(known, stages, 1, skipped, CLAIMS)[0] == [
        "ADC-KRN-001: no passing test is marked with it"
    ]
    problems, notes = trace.check(known, stages, 1, skipped, CLAIMS, named)
    assert problems == [] and any("verified by another run" in n for n in notes)
    failing = {**GOOD, "ADC-KRN-001": {"skipped": ["t"], "failed": ["u"]}}
    assert trace.check(known, stages, 1, failing, CLAIMS, named)[0]
    absent = {"ADC-PRV-001": {"passed": ["t1"]}}
    assert trace.check(known, stages, 1, absent, CLAIMS, named)[0]
    workflow = (REPO / ".github/workflows/pr.yml").read_text(encoding="utf-8")
    assert "--verified-elsewhere ADC-PRV-002" in workflow
    nightly = (REPO / ".github/workflows/nightly.yml").read_text(encoding="utf-8")
    assert "forbidden_terms.py scan-history" in nightly and "secrets.ADC_TERMS_KEY" in nightly


@pytest.mark.req("ADC-CI-001")
def test_no_test_in_the_tree_cites_an_unknown_requirement() -> None:
    assert set(trace.marked_in_tree(REPO)) <= KNOWN


@pytest.mark.req("ADC-CI-001")
def test_every_requirement_due_at_the_current_stage_has_a_marked_test_and_an_owner() -> None:
    due = set().union(*(ids for stage, ids in STAGES.items() if stage <= STAGE))
    marked, claimed = trace.marked_in_tree(REPO), trace.claims(REPO)
    assert sorted(due - set(marked)) == []
    assert sorted(due - set(claimed)) == []
