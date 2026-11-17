"""List the gates registered for a season, as their issues stood at the deadline.

A gate takes part in a season's Track D with the version its registration
issue named at the registration deadline (docs/bench/PUBLIC_TEST.md). An issue
can be edited, so the version is read from the issue's edit history as it was
at that instant, not from the issue as it is now. GitHub keeps that history
and shows it to anyone, so anyone can run this again and get the same list.

    python tools/season_registrations.py --deadline 2026-12-02T12:00:00Z \
        --out docs/bench/season-1-registrations.json

It reads the issues labelled ``gate-registration`` with the GitHub CLI
(``gh``). An issue opened after the deadline is left out. An issue whose text
at the deadline cannot be established from its history is listed with that
said, never guessed.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
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
        number url createdAt body author { login }
        userContentEdits(first: 100) { nodes { editedAt diff } }
      }
    }
  }
}
"""

Query = Callable[[str | None], Mapping[str, Any]]


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def body_at(issue: Mapping[str, Any], deadline: datetime) -> str | None:
    """Return the issue's text as it stood at *deadline*, or None if that cannot be known.

    GitHub lists an issue's edits newest first, each with the full text after
    it; once an issue has been edited, the oldest entry is the text it was
    opened with. An issue never edited has no entries, and its text now is its
    text then.
    """
    edits = sorted(
        (e for e in issue["userContentEdits"]["nodes"] if e.get("diff") is not None),
        key=lambda e: e["editedAt"],
    )
    if not edits:
        return str(issue["body"])
    before = [e for e in edits if _instant(e["editedAt"]) <= deadline]
    return str(before[-1]["diff"]) if before else None


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


def registrations(issues: Sequence[Mapping[str, Any]], deadline: datetime) -> list[dict[str, Any]]:
    """Return one entry per issue opened before *deadline*, with its answers at that instant."""
    listed = []
    for issue in issues:
        if _instant(issue["createdAt"]) > deadline:
            continue
        text = body_at(issue, deadline)
        entry: dict[str, Any] = {
            "issue": issue["number"],
            "url": issue["url"],
            "opened_by": (issue.get("author") or {}).get("login"),
            "opened_at": issue["createdAt"],
        }
        if text is None:
            entry["problem"] = "the text at the deadline is not in the issue's edit history"
        else:
            entry.update(fields(text))
            entry["edited_after_deadline"] = text != issue["body"]
        listed.append(entry)
    return listed


def _gh_query(after: str | None) -> Mapping[str, Any]:
    owner, name = REPOSITORY.split("/")
    command = ["gh", "api", "graphql", "-f", f"query={_QUERY}", "-F", f"owner={owner}",
               "-F", f"name={name}", "-F", f"label={LABEL}"]  # fmt: skip
    if after:
        command += ["-F", f"after={after}"]
    answer = subprocess.run(command, check=True, capture_output=True, text=True).stdout
    return json.loads(answer)["data"]["repository"]["issues"]  # type: ignore[no-any-return]


def fetch(query: Query = _gh_query) -> list[Mapping[str, Any]]:
    """Return every issue with the registration label."""
    issues: list[Mapping[str, Any]] = []
    after = None
    while True:
        page = query(after)
        issues += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            return issues
        after = page["pageInfo"]["endCursor"]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--deadline", required=True, help="ISO 8601, e.g. 2026-12-02T12:00:00Z")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    deadline = _instant(args.deadline)
    listed = registrations(fetch(), deadline)
    record = {"deadline": args.deadline, "repository": REPOSITORY, "registrations": listed}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"{len(listed)} registration(s) as of {args.deadline} written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
