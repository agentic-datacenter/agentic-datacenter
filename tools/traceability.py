"""Requirement traceability (ADC-CI-001).

Reads the design document, the requirement report written by the test run, and
the claims made by modules and packages, and fails when a requirement that
should be closed is not verified.

"Should be closed" follows the staged plan: the design document assigns each
requirement to a stage (section 13), and ``[tool.agentic-datacenter] stage`` in the root
``pyproject.toml`` says which stage the repository has reached. Requirements of
later stages are listed as open, not as failures.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

import yaml

REQ = re.compile(r"ADC-([A-Z]{2,3})-(\d{3})")
SDD = "docs/design/SDD-ADC-001.md"


def sdd_requirements(text: str) -> set[str]:
    """Return every requirement ID the design document defines."""
    return {f"ADC-{a}-{n}" for a, n in REQ.findall(text.replace("\\_", "_"))}


def _expand(cell: str) -> set[str]:
    """Expand a "Requirements closed" cell such as ``KRN-001 to 004, SAF-001``."""
    ids: set[str] = set()
    area = ""
    for match in re.finditer(
        r"(?:([A-Z]{2,3})-)?(\d{3})(?:\s+to\s+(?:[A-Z]{2,3}-)?(\d{3}))?", cell
    ):
        area = match.group(1) or area
        start, end = int(match.group(2)), int(match.group(3) or match.group(2))
        ids |= {f"ADC-{area}-{n:03d}" for n in range(start, end + 1)}
    return ids


def stage_requirements(text: str) -> dict[int, set[str]]:
    """Return the requirements each stage closes, from the table in section 13."""
    section = text.split("## 13. Staged build plan", 1)[1].split("\n## ", 1)[0]
    stages: dict[int, set[str]] = {}
    for line in section.splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) == 4 and cells[0].isdigit():
            stages[int(cells[0])] = _expand(cells[2])
    return stages


def claims(repo: Path) -> dict[str, set[str]]:
    """Return who claims each requirement: modules by manifest, packages by pyproject."""
    out: dict[str, set[str]] = {}
    for manifest in sorted(
        repo.glob("packages/agentic-datacenter-plant/src/agentic_datacenter/plant/**/module.yaml")
    ):
        data = yaml.safe_load(manifest.read_text(encoding="utf-8"))
        for req_id in data.get("requirements", []):
            out.setdefault(req_id, set()).add(data["id"])
    for pyproject in [repo / "pyproject.toml", *sorted(repo.glob("packages/*/pyproject.toml"))]:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        owner = data["project"]["name"]
        for req_id in data.get("tool", {}).get("agentic-datacenter", {}).get("requirements", []):
            out.setdefault(req_id, set()).add(owner)
    return out


def marked_in_tree(repo: Path) -> dict[str, set[str]]:
    """Return the requirement IDs cited by ``req`` markers, with the files citing them."""
    out: dict[str, set[str]] = {}
    files = [*repo.glob("tests/**/*.py"), *repo.glob("packages/*/tests/**/*.py")]
    for path in sorted(files):
        for req_id in re.findall(r'mark\.req\("(ADC-[A-Z]{2,3}-\d{3})"\)', path.read_text("utf-8")):
            out.setdefault(req_id, set()).add(str(path.relative_to(repo)))
    return out


def check(
    known: set[str],
    by_stage: dict[int, set[str]],
    stage: int,
    report: dict[str, dict[str, list[str]]],
    claimed: dict[str, set[str]],
) -> tuple[list[str], list[str]]:
    """Return (problems, notes) for a test run at *stage*."""
    problems: list[str] = []
    notes: list[str] = []
    for req_id in sorted(set(report) - known):
        problems.append(f"{req_id}: cited by a test but not defined in the design document")
    for req_id in sorted(set(claimed) - known):
        problems.append(f"{req_id}: claimed by {sorted(claimed[req_id])} but not defined")
    due = set().union(*(ids for s, ids in by_stage.items() if s <= stage))
    for req_id in sorted(due):
        outcome = report.get(req_id, {})
        if outcome.get("failed"):
            problems.append(f"{req_id}: failing test(s) {outcome['failed']}")
        elif outcome.get("passed"):
            pass
        elif outcome.get("deselected"):
            notes.append(f"{req_id}: verified only by tests not selected in this run")
        else:
            problems.append(f"{req_id}: no passing test is marked with it")
        if req_id not in claimed:
            problems.append(f"{req_id}: not claimed by any module or package")
    unassigned = sorted(known - set().union(*by_stage.values()))
    for req_id in sorted(set(report) - due):
        if report[req_id].get("failed"):
            problems.append(f"{req_id}: failing test(s) {report[req_id]['failed']}")
    if unassigned:
        notes.append("not assigned to a stage in section 13: " + ", ".join(unassigned))
    notes.append(f"open (later stages): {len(known - due - set(unassigned))} requirement(s)")
    return problems, notes


def main(argv: list[str] | None = None) -> int:
    """Check a requirement report and return the exit status."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args(argv)
    text = (args.repo / SDD).read_text(encoding="utf-8")
    root = tomllib.loads((args.repo / "pyproject.toml").read_text(encoding="utf-8"))
    stage = int(root["tool"]["agentic-datacenter"]["stage"])
    report = json.loads(args.report.read_text(encoding="utf-8"))
    problems, notes = check(
        sdd_requirements(text), stage_requirements(text), stage, report, claims(args.repo)
    )
    for note in notes:
        print(f"note: {note}")
    for problem in problems:
        print(f"FAIL: {problem}", file=sys.stderr)
    print(f"stage {stage}: {len(problems)} problem(s)")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
