"""The owner's tool for forbidden terms keeps hashes only, and scans every commit (ADC-PRV-002)."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "forbidden_terms", REPO / "tools/forbidden_terms.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_term_is_kept_as_its_hash_only_and_once(tmp_path: Path) -> None:
    tool = _tool()
    listed = tmp_path / "terms.sha256"
    listed.write_text("# header\n", encoding="utf-8")
    assert tool.add(["ACME  Tower", "acme tower", "one two three four"], listed) == 1
    text = listed.read_text(encoding="utf-8")
    assert "acme" not in text.lower() and tool.digest("acme tower") in text


def test_the_history_scan_finds_a_term_removed_from_the_current_files(tmp_path: Path) -> None:
    tool = _tool()

    def git(*args: str) -> None:
        subprocess.run(["git", "-C", str(tmp_path), *args], check=True, capture_output=True)

    git("init", "-q")
    git("config", "user.email", "t@example.invalid")
    git("config", "user.name", "t")
    (tmp_path / "notes.md").write_text("Built for the ACME Tower project.\n", encoding="utf-8")
    git("add", ".")
    git("commit", "-qm", "one")
    (tmp_path / "notes.md").write_text("Built for a generic site.\n", encoding="utf-8")
    git("commit", "-qam", "two")
    hits = tool.scan_history({tool.digest("acme tower")}, tmp_path)
    assert len(hits) == 1 and hits[0].endswith("notes.md")
    assert tool.scan_history({tool.digest("nothing here")}, tmp_path) == []


@pytest.mark.parametrize("term", ["", "one two three four"])
def test_a_term_must_be_one_to_three_words(term: str) -> None:
    assert _tool().normalize(term) is None
