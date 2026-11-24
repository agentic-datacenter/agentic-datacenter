"""ADC-HST-004: the shirudo vectors are the files of the pin, under shirudo's licence (ADR 0030)."""

import hashlib
import re
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PIN = (REPO / "SHIRUDO_PIN").read_text(encoding="utf-8")
FIXTURES = REPO / "tests/fixtures/shirudo"


def pinned_files() -> dict[str, str]:
    return dict(re.findall(r"^\s+testing/fixtures/keepalive/(\S+)\s+([0-9a-f]{64})\s*$", PIN, re.M))


@pytest.mark.req("ADC-HST-004")
def test_the_pin_names_upstream_one_full_commit_and_the_format() -> None:
    assert re.search(r"^repo:\s+https://github\.com/shirudo-dev/shirudo\s*$", PIN, re.M)
    assert re.search(r"^commit:\s+[0-9a-f]{40}\s*$", PIN, re.M)
    assert re.search(r"^format:\s+shirudo\.keepalive/1\s*$", PIN, re.M)


@pytest.mark.req("ADC-HST-004")
def test_every_copied_file_is_listed_with_its_hash_and_nothing_else_is_copied() -> None:
    files = pinned_files()
    assert files, "SHIRUDO_PIN lists no file"
    copied = {p.name for p in (FIXTURES / "keepalive").iterdir()}
    assert copied == set(files)
    for name, digest in files.items():
        assert hashlib.sha256((FIXTURES / "keepalive" / name).read_bytes()).hexdigest() == digest


@pytest.mark.req("ADC-HST-004")
def test_the_copies_carry_shirudos_licence_and_the_notices_name_it() -> None:
    licence = (FIXTURES / "LICENSE").read_text(encoding="utf-8")
    assert licence.startswith("BSD 2-Clause License")
    assert "Copyright (c) 2026 Authors of shirudo" in licence
    notices = (REPO / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    commit = re.search(r"^commit:\s+([0-9a-f]{40})", PIN, re.M)
    assert commit
    assert "shirudo" in notices and commit.group(1) in notices
    assert "tests/fixtures/shirudo/LICENSE" in notices
