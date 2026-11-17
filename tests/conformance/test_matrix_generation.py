"""ADC-EVD-002: the IEC 62443 matrix is generated from test results."""

import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]


def tool() -> Any:
    spec = importlib.util.spec_from_file_location("matrix", REPO / "tools/gen_62443_matrix.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def row(page: str, name: str) -> str:
    return next(line for line in page.splitlines() if line.startswith(f"| {name}"))


@pytest.mark.req("ADC-EVD-002")
def test_the_result_of_each_row_follows_the_test_report(tmp_path: Path) -> None:
    matrix = tool()
    report = {
        "ADC-NET-001": {"passed": ["a"]},
        "ADC-NET-002": {"passed": ["b", "c"]},
        "ADC-NET-004": {"passed": ["d"]},
        "ADC-NET-003": {"passed": ["e"], "failed": ["f"]},
        "ADC-SUP-004": {"passed": ["g"]},
    }
    path = tmp_path / "report.json"
    path.write_text(json.dumps(report))
    out = tmp_path / "matrix.md"
    assert matrix.main(["--report", str(path), "--out", str(out)]) == 0
    page = out.read_text()
    assert "all listed tests passing" in row(page, "FR 5")
    assert "`ADC-NET-002`: 2 passing" in row(page, "FR 5")
    assert "| failing |" in row(page, "FR 6") and "`ADC-NET-003`: 1 failing" in page
    assert "partly shown" in row(page, "FR 1") and "`ADC-GOV-001`: no test" in page
    assert "| not shown |" in row(page, "FR 3")
    assert "no evidence in the simulator yet" in row(page, "FR 4")
    assert f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}" in page
    del report["ADC-NET-001"]
    assert "partly shown" in row(matrix.render(report, "x"), "FR 5")


@pytest.mark.req("ADC-EVD-002")
def test_the_page_says_what_it_is_not() -> None:
    page = tool().render({}, "x")
    assert "not a certificate" in page and "claims no conformance" in page
    assert "this project's interpretation" in page
    assert "Do not edit" in page.splitlines()[0]


def test_every_evidence_id_is_a_requirement_of_the_design_document() -> None:
    known = set(
        re.findall(r"ADC-[A-Z]{2,3}-\d{3}", (REPO / "docs/design/SDD-ADC-001.md").read_text())
    )
    for _, _, _, evidence, _ in tool().ROWS:
        assert set(evidence) <= known
    assert len(tool().ROWS) == 7


@pytest.mark.req("ADC-EVD-002")
def test_no_matrix_is_kept_in_the_repository() -> None:
    """A committed matrix would be a matrix written by hand the moment the tests change."""
    assert not list((REPO / "docs").rglob("*62443_matrix*"))
