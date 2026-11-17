"""The record that ties what a benchmark made to the code that made it (ADR 0025).

A result card says which benchmark version it was made with, not which commit
of the code, and nothing says whether a card is the file a run wrote. The
record names the commit and the SHA-256 of every file beside it. It proves
nothing by itself: anyone can write one. The workflow that made the run signs
the record, and ``bench verify`` checks the files against it.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

RECORD_SCHEMA = "adc-provenance/v1"
RECORD_NAME = "provenance.json"
CARD_NAME = "result_card.json"


def _files(directory: Path) -> dict[str, str]:
    """Return the SHA-256 of every file under *directory* but the record, by relative path."""
    found = sorted(p for p in directory.rglob("*") if p.is_file() and p.name != RECORD_NAME)
    return {
        p.relative_to(directory).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
        for p in found
    }


def build_record(directory: Path, commit: str) -> dict[str, Any]:
    """Return the record of the result card in *directory*, made by the code at *commit*."""
    card = json.loads((directory / CARD_NAME).read_text(encoding="utf-8"))
    return {
        "schema": RECORD_SCHEMA,
        "product": "Agentic-Datacenter",
        "code_commit": commit,
        "card_schema_version": card.get("schema_version"),
        "benchmark_version": card.get("benchmark_version"),
        "label": card.get("label"),
        "files": _files(directory),
    }


def write_record(directory: Path, commit: str) -> Path:
    """Write the record beside the result card in *directory* and return its path."""
    path = directory / RECORD_NAME
    text = json.dumps(build_record(directory, commit), indent=2, sort_keys=True) + "\n"
    path.write_text(text, encoding="utf-8")
    return path


def verify_record(directory: Path) -> list[str]:
    """Return what in *directory* differs from its record; nothing if it is intact."""
    try:
        record = json.loads((directory / RECORD_NAME).read_text(encoding="utf-8"))
        listed = dict(record["files"])
    except (OSError, ValueError, KeyError, TypeError):
        return [f"{RECORD_NAME} is missing or unreadable"]
    present = _files(directory)
    problems = [f"{name} is not in the record" for name in present if name not in listed]
    for name, expected in listed.items():
        if name not in present:
            problems.append(f"{name} is missing")
        elif present[name] != expected:
            problems.append(f"{name} does not match the hash in the record")
    if not problems:
        card = json.loads((directory / CARD_NAME).read_text(encoding="utf-8"))
        if card.get("benchmark_version") != record.get("benchmark_version"):
            problems.append("the benchmark version of the card is not the record's")
    return sorted(problems)
