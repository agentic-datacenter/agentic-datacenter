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
