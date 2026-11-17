"""ADC-DOC-001: the documentation site is configured strictly and generated pages are current."""

import subprocess
import sys
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.req("ADC-DOC-001")
def test_generated_reference_pages_match_the_code() -> None:
    done = subprocess.run(
        [sys.executable, "tools/gen_reference.py", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr


@pytest.mark.req("ADC-DOC-001")
def test_the_example_result_report_is_what_the_generator_makes_from_its_recording() -> None:
    done = subprocess.run(
        [sys.executable, "tools/demo_example.py", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert done.returncode == 0, done.stderr


@pytest.mark.req("ADC-DOC-001")
def test_the_result_report_is_linked_where_it_is_shown_as_a_page() -> None:
    """A code host shows an HTML file as source, so the links go to the Markdown report."""
    picture = REPO / "docs/media/result-report.png"
    assert picture.read_bytes().startswith(b"\x89PNG") and picture.stat().st_size < 300_000
    report = (REPO / "docs/demo/result-report.md").read_text(encoding="utf-8")
    assert "](../media/result-report.png)](result-report.html)" in report
    assert "](three-scenarios.html)" in report
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "](docs/demo/result-report.md)" in readme
    assert 'src="docs/media/result-report.png"' in readme
    assert "](docs/demo/result-report.html)" not in readme.split("## ")[0], "shown as source"
    index = (REPO / "docs/index.md").read_text(encoding="utf-8")
    assert "](demo/result-report.md)" in index and "](demo/result-report.html)" in index


@pytest.mark.req("ADC-DOC-001")
def test_site_is_built_in_strict_mode_from_the_docs_directory() -> None:
    config = yaml.safe_load((REPO / "mkdocs.yml").read_text(encoding="utf-8"))
    assert config["strict"] is True
    assert config["docs_dir"] == "docs"
    job = yaml.safe_load((REPO / ".github/workflows/pr.yml").read_text("utf-8"))["jobs"]["docs"]
    assert any("mkdocs build --strict" in step.get("run", "") for step in job["steps"])


@pytest.mark.req("ADC-DOC-001")
def test_every_page_in_the_navigation_exists() -> None:
    config = yaml.safe_load((REPO / "mkdocs.yml").read_text(encoding="utf-8"))

    def files(node: object) -> list[str]:
        if isinstance(node, str):
            return [node]
        if isinstance(node, list):
            return [f for item in node for f in files(item)]
        if isinstance(node, dict):
            return [f for item in node.values() for f in files(item)]
        return []

    missing = [f for f in files(config["nav"]) if not (REPO / "docs" / f).is_file()]
    assert missing == []
