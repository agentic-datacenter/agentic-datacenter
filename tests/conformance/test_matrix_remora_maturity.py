"""ADC-PIN-006: a maturity word credited to REMORA is the word of REMORA's own register.

The register is the one the pinned, installed REMORA carries. Every test here
compares with that file, read directly, never with a copy kept in this
repository.
"""

import dataclasses
import hashlib
import importlib.util
import json
import re
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("remora")

from agentic_datacenter_remora.binding import (  # noqa: E402
    PinMismatchError,
    installed_commit,
    pinned_commit,
)
from agentic_datacenter_remora.register import (  # noqa: E402
    Capability,
    RegisterError,
    capability_register,
)

REPO = Path(__file__).resolve().parents[2]
PIN = REPO / "REMORA_PIN"
#: The words the requirement names. The register's own are read from the register.
NAMED_IN_THE_REQUIREMENT = {"ESTABLISHED", "PARTIAL", "NOT_ESTABLISHED"}


def tool() -> Any:
    spec = importlib.util.spec_from_file_location("matrix", REPO / "tools/gen_62443_matrix.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def installed_file() -> Path:
    """The register file inside the installed REMORA, found without the code under test."""
    found = importlib.util.find_spec("remora")
    assert found and found.submodule_search_locations
    return Path(found.submodule_search_locations[0]) / "governance/capability_catalogue_v1.json"


def installed_entries() -> dict[str, dict[str, str]]:
    data = json.loads(installed_file().read_bytes())
    return {entry["id"]: entry for entry in data["capabilities"]}


def credited(page: str) -> list[tuple[str, str, str, str]]:
    """The rows of the table of credited capabilities: row, id, name, maturity word."""
    section = page.split("## REMORA capabilities credited", 1)[1]
    rows = []
    for line in section.splitlines():
        if line.startswith("| FR "):
            row, capability_id, name, word = (c.strip() for c in line.strip("|").split("|"))
            rows.append((row, capability_id.strip("`"), name, word.strip("`")))
    return rows


@pytest.mark.req("ADC-PIN-006")
def test_the_register_is_read_from_the_installed_remora_at_the_pinned_commit(
    tmp_path: Path,
) -> None:
    register = capability_register(PIN)
    assert register.commit == pinned_commit(PIN) == installed_commit()
    assert register.sha256 == hashlib.sha256(installed_file().read_bytes()).hexdigest()
    entries = installed_entries()
    assert len(entries) > 20
    assert {i: (c.name, c.status) for i, c in register.capabilities.items()} == {
        i: (e["name"], e["status"]) for i, e in entries.items()
    }
    other = tmp_path / "REMORA_PIN"
    other.write_text(f"commit:      {'0' * 40}\n")
    with pytest.raises(PinMismatchError):
        capability_register(other)


@pytest.mark.req("ADC-PIN-006")
def test_every_capability_the_matrix_credits_carries_the_word_of_the_register(
    tmp_path: Path,
) -> None:
    matrix = tool()
    report = tmp_path / "report.json"
    report.write_text("{}")
    out = tmp_path / "matrix.md"
    assert matrix.main(["--report", str(report), "--out", str(out)]) == 0
    page = out.read_text()
    rows, entries = credited(page), installed_entries()
    assert {(row[:4], i) for row, i, _, _ in rows} == {
        (row, i) for row, ids in matrix.REMORA_CREDIT.items() for i in ids
    }
    assert len(rows) >= 4
    for _, capability_id, name, word in rows:
        assert word == entries[capability_id]["status"], capability_id
        assert name == entries[capability_id]["name"], capability_id
    assert f"commit `{pinned_commit(PIN)}`" in page
    assert f"sha256:{hashlib.sha256(installed_file().read_bytes()).hexdigest()}" in page
    # No maturity word stands anywhere on the page but in that table.
    words = {e["status"] for e in entries.values()} | NAMED_IN_THE_REQUIREMENT
    outside = "\n".join(line for line in page.splitlines() if not line.startswith("| FR "))
    assert not [w for w in words if re.search(rf"\b{w}\b", outside)]


@pytest.mark.req("ADC-PIN-006")
def test_the_word_on_the_page_follows_the_register_and_nothing_else() -> None:
    """With another word in the register, that word is on the page: none is typed in."""
    matrix = tool()
    register = capability_register(PIN)
    ids = sorted({i for ids in matrix.REMORA_CREDIT.values() for i in ids})
    for number, capability_id in enumerate(ids):
        was = register.capabilities[capability_id]
        changed = dataclasses.replace(
            register,
            capabilities={
                **register.capabilities,
                capability_id: Capability(was.id, was.name, f"WORD_{number}"),
            },
        )
        rows = credited(matrix.render({}, "x", changed))
        assert capability_id in {shown_id for _, shown_id, _, _ in rows}
        for _, shown_id, _, word in rows:
            expected = f"WORD_{number}" if shown_id == capability_id else None
            assert word == (expected or register.maturity(shown_id))


@pytest.mark.req("ADC-PIN-006")
def test_a_capability_the_register_does_not_list_gets_no_word(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    matrix = tool()
    register = capability_register(PIN)
    assert "CAP-999" not in installed_entries()
    with pytest.raises(RegisterError, match="does not list CAP-999"):
        register.maturity("CAP-999")
    monkeypatch.setattr(matrix, "REMORA_CREDIT", {"FR 2": ("CAP-999",)})
    with pytest.raises(RegisterError):
        matrix.render({}, "x", register)


@pytest.mark.req("ADC-PIN-006")
def test_a_matrix_made_at_another_commit_than_the_pin_is_not_written(tmp_path: Path) -> None:
    matrix = tool()
    report = tmp_path / "report.json"
    report.write_text("{}")
    other = tmp_path / "REMORA_PIN"
    other.write_text(f"commit:      {'0' * 40}\n")
    out = tmp_path / "matrix.md"
    arguments = ["--report", str(report), "--out", str(out), "--remora-pin", str(other)]
    assert matrix.main(arguments) == 1
    assert not out.exists()


@pytest.mark.req("ADC-PIN-006")
def test_without_the_register_the_matrix_credits_remora_with_nothing() -> None:
    page = tool().render({}, "x")
    assert "credits REMORA with no capability" in page
    assert credited(page) == []
    words = {e["status"] for e in installed_entries().values()} | NAMED_IN_THE_REQUIREMENT
    assert not [w for w in words if re.search(rf"\b{w}\b", page)]


@pytest.mark.req("ADC-PIN-006")
def test_no_maturity_word_is_typed_into_the_code_or_the_committed_evidence() -> None:
    """The matrix and the evidence bundle can only show a word they were given.

    The evidence bundle credits REMORA with no capability today. This holds it
    to that: a word of the register, or of the requirement, written into any
    source file or into the committed example would be a word not read from
    the register.
    """
    words = {e["status"] for e in installed_entries().values()} | NAMED_IN_THE_REQUIREMENT
    files = [
        *REPO.glob("packages/*/src/**/*.py"),
        *REPO.glob("tools/*.py"),
        *REPO.glob("docs/demo/*.json"),
        *REPO.glob("docs/demo/*.md"),
        *REPO.glob("docs/demo/*.html"),
    ]
    assert len(files) > 100
    hits = [
        f"{path.relative_to(REPO)}: {word}"
        for path in files
        for word in words
        if re.search(rf"\b{word}\b", path.read_text(encoding="utf-8"))
    ]
    assert hits == []
