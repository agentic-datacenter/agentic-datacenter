"""The registry of operational findings: valid, searchable, and stale when an input changes."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("findings", REPO / "tools/findings.py")
assert _spec and _spec.loader
findings = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(findings)
FIRST = yaml.safe_load((REPO / "findings/ADC-FIND-0001.yaml").read_text(encoding="utf-8"))


@pytest.mark.req("ADC-FND-001")
def test_every_finding_is_valid_current_and_on_its_page() -> None:
    assert findings.main(["--check"]) == 0
    page = (REPO / "docs/reference/findings.md").read_text(encoding="utf-8")
    assert "ADC-FIND-0001" in page and "| no |" in page


@pytest.mark.req("ADC-FND-001")
@pytest.mark.parametrize(
    ("change", "problem"),
    [
        ({"claim": None}, None),
        ({"status": "proven"}, "status must be one of"),
        ({"visibility": "private"}, "only public findings"),
        ({"evidence_refs": [{"path": "docs/demo/demo.json", "sha256": "0" * 64}]},
         "does not match its sha256"),
        ({"status": "replicated"}, "names its independent replications"),
        ({"credited_to": []}, "credit at least one contributor"),
    ],
)  # fmt: skip
def test_a_finding_that_does_not_hold_together_is_refused(
    change: dict[str, Any], problem: str | None
) -> None:
    finding = {**copy.deepcopy(FIRST), **change}
    if change == {"claim": None}:
        finding.pop("claim")
        problem = "claim is required"
    found = findings.problems(finding, "ADC-FIND-0001", REPO)
    assert any(problem in p for p in found), found


@pytest.mark.req("ADC-FND-002")
def test_a_changed_input_makes_a_finding_stale() -> None:
    now = findings.current_hashes()
    assert findings.stale(FIRST, now) == []
    moved = copy.deepcopy(FIRST)
    moved["depends_on"]["scenarios"]["OP-03"] = "0" * 64
    assert findings.stale(moved, now) == ["scenarios/OP-03"]


@pytest.mark.req("ADC-FND-002")
def test_a_settled_finding_that_is_stale_fails_the_check(tmp_path: Path) -> None:
    for status, expected in (("supported", 1), ("hypothesis", 0)):
        moved = {**copy.deepcopy(FIRST), "status": status, "visibility": "private",
                 "evidence_refs": []}  # fmt: skip
        if status == "supported":
            moved["evidence_refs"] = [{"path": "e.json", "sha256": findings._sha256(
                REPO / "docs/demo/demo.json")}]  # fmt: skip
            (tmp_path / "e.json").write_bytes((REPO / "docs/demo/demo.json").read_bytes())
        moved["depends_on"]["scenarios"]["OP-03"] = "0" * 64
        (tmp_path / "ADC-FIND-0001.yaml").write_text(yaml.safe_dump(moved))
        assert findings.main(["--dir", str(tmp_path), "--check"]) == expected, status


@pytest.mark.req("ADC-FND-003")
def test_findings_are_found_by_scenario_gate_and_class() -> None:
    every = findings.load()
    assert findings.search(every, scenario="OP-03", gate="remora_governed") == [FIRST]
    assert findings.search(every, scenario="AD-15") == []
    assert findings.search(every, facility_class="generic_air_cooled_f1") == [FIRST]
