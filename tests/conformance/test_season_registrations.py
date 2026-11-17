"""A season's registrations are read as they stood at the deadline (docs/bench/PUBLIC_TEST.md)."""

from __future__ import annotations

import importlib.util
from datetime import datetime
from pathlib import Path
from types import ModuleType
from typing import Any

REPO = Path(__file__).resolve().parents[2]
DEADLINE = datetime.fromisoformat("2026-12-02T12:00:00+00:00")


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "season_registrations", REPO / "tools/season_registrations.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _body(version: str) -> str:
    # As GitHub writes an issue form's answers.
    return (
        "### 01 · Project / gate name\n\nMy Gate\n\n"
        f"### 02 · Exact version (must be fixed)\n\n{version}\n\n"
        "### 03 · How will you connect it?\n\nHTTP service (http_gate)\n\n"
        "### Project URL (optional)\n\n_No response_\n"
    )


def _issue(number: int, opened: str, body: str, edits: list[tuple[str, str]]) -> dict[str, Any]:
    return {
        "number": number, "url": f"https://example.invalid/{number}", "createdAt": opened,
        "author": {"login": "someone"}, "body": body,
        "userContentEdits": {"nodes": [{"editedAt": t, "diff": d} for t, d in reversed(edits)]},
    }  # fmt: skip


def test_the_form_answers_are_read_from_the_issue_text() -> None:
    answers = _tool().fields(_body("abc123"))
    assert answers == {
        "gate": "My Gate", "version": "abc123", "attached": "HTTP service (http_gate)",
        "project_url": "",
    }  # fmt: skip


def test_an_edit_after_the_deadline_does_not_change_the_registered_version() -> None:
    issue = _issue(1, "2026-11-20T10:00:00Z", _body("new"), [
        ("2026-11-20T10:00:00Z", _body("first")),
        ("2026-11-25T10:00:00Z", _body("second")),
        ("2026-12-03T10:00:00Z", _body("new")),
    ])  # fmt: skip
    (entry,) = _tool().registrations([issue], DEADLINE)
    assert entry["version"] == "second"
    assert entry["edited_after_deadline"] is True


def test_an_issue_never_edited_is_read_as_it_is() -> None:
    (entry,) = _tool().registrations([_issue(2, "2026-11-20T10:00:00Z", _body("v1"), [])], DEADLINE)
    assert entry["version"] == "v1" and entry["edited_after_deadline"] is False


def test_an_issue_opened_after_the_deadline_is_left_out() -> None:
    late = _issue(3, "2026-12-02T12:00:01Z", _body("v1"), [])
    assert _tool().registrations([late], DEADLINE) == []


def test_a_text_that_cannot_be_established_is_said_and_not_guessed() -> None:
    # Edited only after the deadline, and the history lacks the opening text.
    issue = _issue(
        4, "2026-11-20T10:00:00Z", _body("late"), [("2026-12-05T10:00:00Z", _body("late"))]
    )
    (entry,) = _tool().registrations([issue], DEADLINE)
    assert "problem" in entry and "version" not in entry


def test_every_page_of_issues_is_read() -> None:
    pages = {
        None: {"nodes": [{"n": 1}], "pageInfo": {"hasNextPage": True, "endCursor": "c1"}},
        "c1": {"nodes": [{"n": 2}], "pageInfo": {"hasNextPage": False, "endCursor": None}},
    }
    assert _tool().fetch(lambda after: pages[after]) == [{"n": 1}, {"n": 2}]


def test_the_headings_it_reads_are_the_forms_own() -> None:
    form = (REPO / ".github/ISSUE_TEMPLATE/gate-registration.yml").read_text(encoding="utf-8")
    for words in _tool().FIELDS.values():
        assert words in form, words
