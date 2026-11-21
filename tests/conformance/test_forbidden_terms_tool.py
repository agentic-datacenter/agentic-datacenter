"""The tool for forbidden terms keeps keyed hashes only, and scans every commit (ADC-PRV-002)."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest

REPO = Path(__file__).resolve().parents[2]
KEY = b"0123456789abcdef"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "forbidden_terms", REPO / "tools/forbidden_terms.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_term_is_kept_as_its_keyed_hash_only_and_once(tmp_path: Path) -> None:
    tool = _tool()
    listed = tmp_path / "terms.hmac"
    listed.write_text("# header\n", encoding="utf-8")
    assert tool.add(["ACME  Tower", "acme tower", "one two three four"], KEY, listed) == 1
    text = listed.read_text(encoding="utf-8")
    assert "acme" not in text.lower() and tool.digest(KEY, "acme tower") in text
    assert tool.listed_key_id(listed) == tool.key_id(KEY)


def test_a_guess_without_the_key_does_not_match(tmp_path: Path) -> None:
    import hashlib

    tool = _tool()
    listed = tmp_path / "terms.hmac"
    tool.add(["acme tower"], KEY, listed)
    assert hashlib.sha256(b"acme tower").hexdigest() not in tool.known(listed)


def test_the_list_refuses_another_key(tmp_path: Path) -> None:
    tool = _tool()
    listed = tmp_path / "terms.hmac"
    tool.add(["acme tower"], KEY, listed)
    with pytest.raises(tool.TermsKeyError):
        tool.add(["other"], b"another key", listed)
    with pytest.raises(tool.TermsKeyError):
        tool.check_key(None, listed)


def test_the_key_comes_from_the_environment_before_the_file(tmp_path: Path) -> None:
    tool = _tool()
    keyfile = tool.init_key(tmp_path / "k" / "key")
    assert keyfile.stat().st_mode & 0o077 == 0
    assert tool.read_key({}, keyfile) == keyfile.read_text(encoding="utf-8").strip().encode()
    assert tool.read_key({"ADC_TERMS_KEY": "abc"}, keyfile) == b"abc"
    assert tool.read_key({}, tmp_path / "missing") is None


def test_the_history_scan_finds_a_term_removed_from_the_files_and_in_messages(
    tmp_path: Path,
) -> None:
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
    git("commit", "-qam", "two, not for Globex Plaza")
    hits = tool.scan_history({tool.digest(KEY, "acme tower")}, KEY, tmp_path)
    assert len(hits) == 1 and hits[0].endswith("notes.md")
    message = tool.scan_history({tool.digest(KEY, "globex plaza")}, KEY, tmp_path)
    assert len(message) == 1 and message[0].endswith("(commit message)")
    assert tool.scan_history({tool.digest(KEY, "nothing here")}, KEY, tmp_path) == []
    assert tool.scan_files({tool.digest(KEY, "acme tower")}, KEY, tmp_path) == []


@pytest.mark.parametrize("term", ["", "one two three four"])
def test_a_term_must_be_one_to_three_words(term: str) -> None:
    assert _tool().normalize(term) is None
