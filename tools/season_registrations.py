"""List the gates registered for a season, as their issues stood at the deadline.

A gate takes part in a season's Track D with the version its registration
issue named at the registration deadline (docs/bench/PUBLIC_TEST.md). An issue
can be edited, so the version is read from the issue's edit history as it was
at that instant, not from the issue as it is now. GitHub keeps that history
and shows it to anyone, so anyone can run this again and get the same list.

    python tools/season_registrations.py --season 2

A registration stands for every season until its issue is closed, so from
season 2 on an issue closed by a season's deadline is left out of that
season. ``--season`` reads the deadline from the plan (``tools/season.py``)
and writes ``docs/bench/season-<n>-registrations.json``. A deadline can also be
given by itself:

    python tools/season_registrations.py --deadline 2027-01-13T12:00:00Z \
        --out docs/bench/season-1-registrations.json

It reads the issues labelled ``gate-registration`` with the GitHub CLI
(``gh``). An issue opened after the deadline is left out.

Nothing is guessed. An issue is listed with a problem, and without a version,
when what it was at the deadline cannot be established:

- Whether it was open is read from its close and reopen events, not from
  whether it is closed today: an issue closed at the deadline and opened again
  later is open now.
- Its text is read from the entries of its edit history, each taken as the
  whole text after an edit. That reading is checked on every edited issue:
  the newest entry must be the issue's text as it is. If it is not, the
  entries are something else, and no version is given.
- An entry can be removed from the history. If the one that held the text at
  the deadline is gone, the entry before it is not the answer.
- A history longer than one page is read to its end.

The text at the deadline is listed with its SHA-256.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

REPOSITORY = "darklordVirtual/agentic-datacenter"
LABEL = "gate-registration"
#: The form's headings (.github/ISSUE_TEMPLATE/gate-registration.yml), by field.
FIELDS = {
    "gate": "Project / gate name",
    "version": "Exact version",
    "attached": "How will you connect it?",
    "project_url": "Project URL",
}
_QUERY = """
query($owner: String!, $name: String!, $label: String!, $after: String) {
  repository(owner: $owner, name: $name) {
    issues(labels: [$label], first: 50, after: $after,
           orderBy: {field: CREATED_AT, direction: ASC}) {
      pageInfo { hasNextPage endCursor }
      nodes {
        number url createdAt closedAt body author { login }
        userContentEdits(first: 100) {
          totalCount pageInfo { hasNextPage endCursor }
          nodes { editedAt deletedAt diff }
        }
        timelineItems(itemTypes: [CLOSED_EVENT, REOPENED_EVENT], first: 100) {
          totalCount
          nodes {
            __typename
            ... on ClosedEvent { createdAt }
            ... on ReopenedEvent { createdAt }
          }
        }
      }
    }
  }
}
"""
_EDITS_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $after: String!) {
  repository(owner: $owner, name: $name) {
    issue(number: $number) {
      userContentEdits(first: 100, after: $after) {
        totalCount pageInfo { hasNextPage endCursor }
        nodes { editedAt deletedAt diff }
      }
    }
  }
}
"""

Query = Callable[[str | None], Mapping[str, Any]]
MoreEdits = Callable[[int, str], Mapping[str, Any]]


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _same(one: str, other: str) -> bool:
    """Whether two texts are the same but for how their lines end."""
    return one.replace("\r\n", "\n").rstrip() == other.replace("\r\n", "\n").rstrip()


def text_at(issue: Mapping[str, Any], deadline: datetime) -> tuple[str | None, str | None]:
    """Return the issue's text as it stood at *deadline*, or why it cannot be known.

    GitHub lists an issue's edits newest first. Each entry is read as the
    whole text after that edit; once an issue has been edited, the oldest
    entry is the text it was opened with. An issue never edited has no
    entries, and its text now is its text then.
    """
    history = issue["userContentEdits"]
    entries = sorted(history["nodes"], key=lambda e: e["editedAt"])
    total = int(history.get("totalCount", len(entries)))
    if total == 0 and not entries:
        return str(issue["body"]), None
    newest = entries[-1].get("diff") if entries else None
    if newest is not None and not _same(str(newest), str(issue["body"])):
        return None, (
            "the newest entry of the edit history is not the issue's text as it is, "
            "so an entry is not the whole text after an edit"
        )
    before = [e for e in entries if _instant(e["editedAt"]) <= deadline]
    if not before:
        if len(entries) < total:
            return None, (
                f"only {len(entries)} of {total} entries of the edit history were read, "
                "none of them from before the deadline"
            )
        return None, "the text at the deadline is not in the issue's edit history"
    if before[-1].get("diff") is None:
        return (
            None,
            "the entry that held the text at the deadline was removed from the edit history",
        )
    return str(before[-1]["diff"]), None


def open_at(issue: Mapping[str, Any], deadline: datetime) -> tuple[bool | None, str | None]:
    """Return whether the issue was open at *deadline*, or why it cannot be known.

    Read from the issue's close and reopen events. ``closedAt`` says only when
    an issue that is closed today was last closed; it is used when the events
    were not asked for.
    """
    timeline = issue.get("timelineItems")
    if timeline is None:
        closed = issue.get("closedAt")
        return not (closed and _instant(closed) <= deadline), None
    events = sorted(timeline["nodes"], key=lambda e: e["createdAt"])
    if int(timeline.get("totalCount", len(events))) > len(events):
        return None, "the issue has more close and reopen events than were read"
    before = [e for e in events if _instant(e["createdAt"]) <= deadline]
    return not (before and before[-1]["__typename"] == "ClosedEvent"), None


def fields(body: str) -> dict[str, str]:
    """Return the form's answers from an issue's text, by field."""
    sections = re.split(r"(?m)^###\s+", body)
    answers: dict[str, str] = {}
    for section in sections[1:]:
        heading, _, value = section.partition("\n")
        for field, words in FIELDS.items():
            if words in heading and field not in answers:
                value = value.strip()
                answers[field] = "" if value == "_No response_" else value
    return answers


def registrations(
    issues: Sequence[Mapping[str, Any]], deadline: datetime, standing: bool = False
) -> list[dict[str, Any]]:
    """Return one entry per issue opened before *deadline*, with its answers at that instant.

    With *standing*, an issue that was closed at the deadline is left out: a
    registration stands for every season until its issue is closed. An issue
    whose state or text at the deadline cannot be established is always
    listed, with the problem and without a version.
    """
    listed = []
    for issue in issues:
        if _instant(issue["createdAt"]) > deadline:
            continue
        was_open, state_problem = open_at(issue, deadline)
        if standing and was_open is False:
            continue
        text, text_problem = text_at(issue, deadline)
        history = issue["userContentEdits"]
        entry: dict[str, Any] = {
            "issue": issue["number"],
            "url": issue["url"],
            "opened_by": (issue.get("author") or {}).get("login"),
            "opened_at": issue["createdAt"],
            "closed_at": issue.get("closedAt"),
            "edits_read": len(history["nodes"]),
            "edits_in_history": int(history.get("totalCount", len(history["nodes"]))),
        }
        if was_open is not None:
            entry["open_at_deadline"] = was_open
        problems = [p for p in (state_problem, text_problem) if p]
        if problems:
            entry["problem"] = "; ".join(problems)
        elif text is not None:
            entry.update(fields(text))
            entry["text_sha256"] = hashlib.sha256(text.encode("utf-8")).hexdigest()
            entry["edited_after_deadline"] = not _same(text, str(issue["body"]))
        listed.append(entry)
    return listed


def _gh(query: str, *variables: str) -> Mapping[str, Any]:
    owner, name = REPOSITORY.split("/")
    command = ["gh", "api", "graphql", "-f", f"query={query}", "-F", f"owner={owner}",
               "-F", f"name={name}", *variables]  # fmt: skip
    answer = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return json.loads(answer)["data"]["repository"]  # type: ignore[no-any-return]


def _gh_query(after: str | None) -> Mapping[str, Any]:
    variables = ["-F", f"label={LABEL}"] + (["-F", f"after={after}"] if after else [])
    return _gh(_QUERY, *variables)["issues"]  # type: ignore[no-any-return]


def _gh_edits(number: int, after: str) -> Mapping[str, Any]:
    found = _gh(_EDITS_QUERY, "-F", f"number={number}", "-F", f"after={after}")
    return found["issue"]["userContentEdits"]  # type: ignore[no-any-return]


def fetch(query: Query = _gh_query, more_edits: MoreEdits = _gh_edits) -> list[Mapping[str, Any]]:
    """Return every issue with the registration label, each with its whole edit history."""
    issues: list[Mapping[str, Any]] = []
    after = None
    while True:
        page = query(after)
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        after = page["pageInfo"]["endCursor"]
    for issue in issues:
        history = issue.get("userContentEdits") or {}
        where = history.get("pageInfo") or {}
        while where.get("hasNextPage"):
            more = more_edits(int(issue["number"]), str(where["endCursor"]))
            history["nodes"] += more["nodes"]  # type: ignore[index]
            where = more["pageInfo"]
        if where:
            history["pageInfo"] = where  # type: ignore[index]
    return issues


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--season", type=int, help="A season of the plan (tools/season.py).")
    which.add_argument("--deadline", help="ISO 8601, e.g. 2027-01-13T12:00:00Z")
    parser.add_argument("--out", type=Path, help="Required with --deadline.")
    args = parser.parse_args(argv)
    record: dict[str, Any] = {"repository": REPOSITORY}
    standing = False
    if args.season is not None:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from season import season  # noqa: PLC0415

        planned = season(args.season)
        args.deadline = planned["deadline"]
        # Season 1 was published before registrations stood from season to season.
        standing = args.season > 1
        args.out = args.out or Path(f"docs/bench/season-{args.season}-registrations.json")
        record.update(season=args.season, opened=planned["opens"], round=planned["round"])
    elif args.out is None:
        parser.error("--out is required with --deadline")
    deadline = _instant(args.deadline)
    listed = registrations(fetch(), deadline, standing)
    record.update(deadline=args.deadline, registrations=listed)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(listed)} registration(s) as of {args.deadline} written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
