"""The record that ties a result card to the code that made it (ADR 0025)."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from agentic_datacenter.scenarios.provenance import (
    RECORD_NAME,
    RECORD_SCHEMA,
    build_record,
    verify_record,
    write_record,
)

from agentic_datacenter.scenarios.cli import bench

COMMIT = "0123456789abcdef0123456789abcdef01234567"
VERSION = {"profile": "aa", "scenario_library": "bb", "oracle": "cc", "frozen": False}
CARD = {
    "schema_version": 5,
    "benchmark_version": VERSION,
    "label": "development run, not a benchmark result",
}


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@pytest.fixture
def out(tmp_path: Path) -> Path:
    directory = tmp_path / "bench"
    (directory / "evidence" / "OP-03").mkdir(parents=True)
    (directory / "result_card.json").write_text(json.dumps(CARD) + "\n", encoding="utf-8")
    (directory / "report.html").write_text("<p>report</p>\n", encoding="utf-8")
    (directory / "evidence" / "OP-03" / "manifest.json").write_text("{}\n", encoding="utf-8")
    return directory


def test_the_record_names_the_commit_the_version_and_the_hash_of_every_file(out: Path) -> None:
    record = build_record(out, COMMIT)
    assert record["schema"] == RECORD_SCHEMA == "adc-provenance/v1"
    assert record["code_commit"] == COMMIT
    assert record["benchmark_version"] == VERSION
    assert record["card_schema_version"] == 5
    assert record["label"] == "development run, not a benchmark result"
    assert record["files"] == {
        "evidence/OP-03/manifest.json": sha(out / "evidence/OP-03/manifest.json"),
        "report.html": sha(out / "report.html"),
        "result_card.json": sha(out / "result_card.json"),
    }


def test_a_record_written_twice_is_the_same_and_does_not_list_itself(out: Path) -> None:
    first = write_record(out, COMMIT).read_bytes()
    assert write_record(out, COMMIT).read_bytes() == first
    assert RECORD_NAME == "provenance.json"
    assert RECORD_NAME not in json.loads(first)["files"]
    assert verify_record(out) == []


def test_a_commit_with_uncommitted_changes_is_recorded_as_such(out: Path) -> None:
    assert build_record(out, COMMIT + "+dirty")["code_commit"] == COMMIT + "+dirty"


def test_a_directory_without_a_result_card_gets_no_record(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        build_record(tmp_path, COMMIT)


def test_a_changed_a_missing_and_an_added_file_are_each_named(out: Path) -> None:
    write_record(out, COMMIT)
    (out / "report.html").write_text("<p>another</p>\n", encoding="utf-8")
    (out / "evidence" / "OP-03" / "manifest.json").unlink()
    (out / "added.txt").write_text("x", encoding="utf-8")
    assert verify_record(out) == [
        "added.txt is not in the record",
        "evidence/OP-03/manifest.json is missing",
        "report.html does not match the hash in the record",
    ]


def test_a_card_of_another_benchmark_version_than_the_record_is_named(out: Path) -> None:
    path = write_record(out, COMMIT)
    record = json.loads(path.read_text(encoding="utf-8"))
    record["benchmark_version"] = {**VERSION, "oracle": "dd"}
    path.write_text(json.dumps(record), encoding="utf-8")
    assert verify_record(out) == ["the benchmark version of the card is not the record's"]


def test_a_missing_or_unreadable_record_is_named(out: Path) -> None:
    assert verify_record(out) == ["provenance.json is missing or unreadable"]
    (out / RECORD_NAME).write_text("not json", encoding="utf-8")
    assert verify_record(out) == ["provenance.json is missing or unreadable"]


def test_the_commands_write_the_record_and_check_it(
    out: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert bench(["record", str(out)]) == 0
    record = json.loads((out / RECORD_NAME).read_text(encoding="utf-8"))
    assert set(record["files"]) == {
        "evidence/OP-03/manifest.json", "report.html", "result_card.json",
    }  # fmt: skip
    assert bench(["verify", str(out)]) == 0
    assert "intact" in capsys.readouterr().out
    (out / "result_card.json").write_text("{}\n", encoding="utf-8")
    assert bench(["verify", str(out)]) == 1
    printed = capsys.readouterr()
    assert "NOT intact" in printed.out
    assert "result_card.json does not match the hash in the record" in printed.err


def test_the_record_command_refuses_a_directory_without_a_card(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert bench(["record", str(tmp_path)]) == 1
    assert "result_card.json" in capsys.readouterr().err
    assert not (tmp_path / RECORD_NAME).exists()
