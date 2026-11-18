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


# --- what the history must stand up to ---------------------------------------


def _events(*pairs: tuple[str, str]) -> dict[str, Any]:
    kinds = {"closed": "ClosedEvent", "reopened": "ReopenedEvent"}
    nodes = [{"__typename": kinds[kind], "createdAt": at} for kind, at in pairs]
    return {"totalCount": len(nodes), "nodes": nodes}


def _history(issue: dict[str, Any], *pairs: tuple[str, str], closed_now: str | None = None) -> Any:
    return {**issue, "timelineItems": _events(*pairs), "closedAt": closed_now}


def _standing(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _tool().registrations(issues, DEADLINE, standing=True)  # type: ignore[no-any-return]


def test_an_issue_closed_at_the_deadline_and_opened_again_later_was_not_registered() -> None:
    """The issue is open today, so its closing date is empty. Only its events say what it was."""
    issue = _history(
        _issue(10, "2026-11-20T10:00:00Z", _body("v1"), []),
        ("closed", "2026-11-30T10:00:00Z"), ("reopened", "2026-12-05T10:00:00Z"),
    )  # fmt: skip
    assert _standing([issue]) == []
    (entry,) = _tool().registrations([issue], DEADLINE)
    assert entry["open_at_deadline"] is False


def test_an_issue_closed_and_opened_again_before_the_deadline_was_registered() -> None:
    issue = _history(
        _issue(11, "2026-11-20T10:00:00Z", _body("v1"), []),
        ("closed", "2026-11-25T10:00:00Z"), ("reopened", "2026-11-26T10:00:00Z"),
    )  # fmt: skip
    (entry,) = _standing([issue])
    assert entry["open_at_deadline"] is True and entry["version"] == "v1"


def test_an_issue_closed_after_the_deadline_was_registered() -> None:
    issue = _history(
        _issue(12, "2026-11-20T10:00:00Z", _body("v1"), []),
        ("closed", "2026-12-03T10:00:00Z"), closed_now="2026-12-03T10:00:00Z",
    )  # fmt: skip
    (entry,) = _standing([issue])
    assert entry["open_at_deadline"] is True


def test_events_given_in_any_order_are_read_by_their_time() -> None:
    issue = _history(
        _issue(13, "2026-11-20T10:00:00Z", _body("v1"), []),
        ("reopened", "2026-11-26T10:00:00Z"), ("closed", "2026-11-28T10:00:00Z"),
        ("closed", "2026-11-25T10:00:00Z"),
    )  # fmt: skip
    assert _standing([issue]) == []


def test_more_close_events_than_were_read_is_said_and_not_guessed() -> None:
    issue = _history(
        _issue(14, "2026-11-20T10:00:00Z", _body("v1"), []), ("closed", "2026-11-25T10:00:00Z")
    )
    issue["timelineItems"]["totalCount"] = 150
    (entry,) = _standing([issue])
    assert "problem" in entry and "open_at_deadline" not in entry


def test_of_several_edits_the_last_one_before_the_deadline_counts() -> None:
    edits = [(f"2026-11-{day:02d}T10:00:00Z", _body(f"v{day}")) for day in range(20, 30)]
    edits += [
        ("2026-12-02T12:00:00Z", _body("at the deadline")),
        ("2026-12-02T12:00:01Z", _body("late")),
    ]
    (entry,) = _standing([_issue(15, "2026-11-20T10:00:00Z", _body("late"), edits)])
    assert entry["version"] == "at the deadline"
    assert entry["edited_after_deadline"] is True
    assert entry["edits_read"] == entry["edits_in_history"] == 12


def test_the_text_at_the_deadline_is_listed_with_its_hash() -> None:
    import hashlib

    (entry,) = _standing([_issue(16, "2026-11-20T10:00:00Z", _body("v1"), [])])
    assert entry["text_sha256"] == hashlib.sha256(_body("v1").encode("utf-8")).hexdigest()


def test_a_history_that_does_not_hold_whole_texts_is_said_and_not_guessed() -> None:
    """The tool reads each entry as the whole text after an edit. If the newest
    entry is not the issue as it is, that reading is wrong, and no version is given."""
    issue = _issue(17, "2026-11-20T10:00:00Z", _body("v2"), [
        ("2026-11-20T10:00:00Z", _body("v1")),
        ("2026-11-25T10:00:00Z", "@@ -1 +1 @@\n-v1\n+v2"),
    ])  # fmt: skip
    (entry,) = _standing([issue])
    assert "whole text" in entry["problem"] and "version" not in entry


def test_line_endings_do_not_make_a_history_look_wrong() -> None:
    body = _body("v2")
    issue = _issue(18, "2026-11-20T10:00:00Z", body.replace("\n", "\r\n"), [
        ("2026-11-20T10:00:00Z", _body("v1")), ("2026-11-25T10:00:00Z", body),
    ])  # fmt: skip
    (entry,) = _standing([issue])
    assert entry["version"] == "v2"


def test_an_entry_removed_from_the_history_is_said_and_not_guessed() -> None:
    """An edit can be deleted from an issue's history. The text before it is not the answer."""
    issue = _issue(19, "2026-11-20T10:00:00Z", _body("v3"), [
        ("2026-11-20T10:00:00Z", _body("v1")),
        ("2026-11-25T10:00:00Z", _body("v2")),
        ("2026-12-05T10:00:00Z", _body("v3")),
    ])  # fmt: skip
    removed = next(
        e for e in issue["userContentEdits"]["nodes"] if e["editedAt"].startswith("2026-11-25")
    )
    removed.update(diff=None, deletedAt="2026-12-06T10:00:00Z")
    (entry,) = _standing([issue])
    assert "removed" in entry["problem"] and "version" not in entry


def test_an_entry_removed_after_the_one_that_counts_changes_nothing() -> None:
    issue = _issue(20, "2026-11-20T10:00:00Z", _body("v3"), [
        ("2026-11-20T10:00:00Z", _body("v1")),
        ("2026-12-04T10:00:00Z", _body("v2")),
        ("2026-12-05T10:00:00Z", _body("v3")),
    ])  # fmt: skip
    removed = next(
        e for e in issue["userContentEdits"]["nodes"] if e["editedAt"].startswith("2026-12-04")
    )
    removed.update(diff=None, deletedAt="2026-12-06T10:00:00Z")
    (entry,) = _standing([issue])
    assert entry["version"] == "v1"


def _many_edits(count: int) -> list[tuple[str, str]]:
    """One edit a minute from the opening; the first *count* - 1 fall before the deadline."""
    from datetime import timedelta

    first = datetime.fromisoformat("2026-11-20T10:00:00+00:00")
    stamps = [
        (first + timedelta(minutes=i)).strftime("%Y-%m-%dT%H:%M:%SZ") for i in range(count - 1)
    ]
    return [(at, _body(f"v{i}")) for i, at in enumerate(stamps)] + [
        ("2026-12-03T10:00:00Z", _body("late"))
    ]


def test_an_issue_with_more_edits_than_one_page_is_read_to_the_end() -> None:
    edits = _many_edits(230)
    issue = _issue(21, "2026-11-20T10:00:00Z", _body("late"), edits)
    newest_first = issue["userContentEdits"]["nodes"]
    pages = [newest_first[i : i + 100] for i in range(0, len(newest_first), 100)]
    issue["userContentEdits"] = {
        "totalCount": 230, "nodes": pages[0],
        "pageInfo": {"hasNextPage": True, "endCursor": "p1"},
    }  # fmt: skip
    asked: list[tuple[int, str]] = []

    def more(number: int, after: str) -> dict[str, Any]:
        asked.append((number, after))
        index = int(after[1:])
        last = index == len(pages) - 1
        return {
            "totalCount": 230, "nodes": pages[index],
            "pageInfo": {"hasNextPage": not last, "endCursor": None if last else f"p{index + 1}"},
        }  # fmt: skip

    page = {"nodes": [issue], "pageInfo": {"hasNextPage": False, "endCursor": None}}
    (read,) = _tool().fetch(lambda after: page, more)
    assert asked == [(21, "p1"), (21, "p2")]
    (entry,) = _standing([read])
    assert entry["version"] == "v228" and entry["edits_read"] == entry["edits_in_history"] == 230


def test_a_history_read_in_part_is_said_when_the_part_does_not_reach_the_deadline() -> None:
    edits = _many_edits(230)
    issue = _issue(22, "2026-11-20T10:00:00Z", _body("late"), edits)
    issue["userContentEdits"] = {"totalCount": 230, "nodes": issue["userContentEdits"]["nodes"][:1]}
    (entry,) = _standing([issue])
    assert "problem" in entry and entry["edits_read"] == 1 and entry["edits_in_history"] == 230


def test_the_query_asks_for_the_events_and_the_whole_history() -> None:
    query = _tool()._QUERY
    for word in ("CLOSED_EVENT", "REOPENED_EVENT", "totalCount", "deletedAt", "hasNextPage"):
        assert word in query, word
