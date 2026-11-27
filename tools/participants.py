"""The table of governance systems that have enrolled, their results side by side, and findings.

    python tools/participants.py            # writes docs/bench/participants.md
    python tools/participants.py --check    # fails if it is not up to date, or an entry is wrong

A system is named here only after it enrolled itself: each entry in
``docs/bench/participants/<id>.yaml`` names the registration issue its
maintainers opened in this repository and their consent to be listed by name.
No entry, no name.

Each entry may list result cards. The table shows each system's figures from
its latest card, beside the built-in gates that ran on the same card, so a
reader compares like with like. Findings, a weakness seen in a run, are
listed once the maintainers have been told and either have fixed it or agreed
to its publication. Until then a finding is kept as ``reported_privately`` and
counted, not described.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
ENTRIES = REPO / "docs/bench/participants"
PAGE = REPO / "docs/bench/participants.md"
ISSUE = re.compile(r"https://github\.com/agentic-datacenter/agentic-datacenter/issues/\d+")
RELATIONS = ("independent", "benchmark_authors")
CONNECTIONS = ("http_gate", "command_gate", "package", "chain_gate member")
KINDS = ("verified", "self_reported")
STATUSES = ("reported_privately", "open", "fixed", "wont_fix")
#: The figures of the table, from a card's result row, and their heading.
FIGURES = (
    ("unsafe_execution_rate", "Harmful let through"),
    ("false_block_rate", "Safe blocked"),
    ("safety", "Scenarios without harm"),
    ("approvals_per_24h", "Approvals per 24 h"),
)
#: The reference controls every card is compared with: no control, and limits only.
#: They belong to no governance system. A system of this project's authors is an
#: entry like any other, and says so in ``relation``.
BUILT_IN = ("null_gate", "static_allowlist")
#: What a system brings. One system may bring several.
PROVIDES = {
    "decisions": "decides on each proposed action",
    "findings": "states what it found, such as whether a mandate holds, without deciding",
    "evidence": "gives records or receipts of its own that others can check",
    "verification": "checks evidence that this project or another system made",
}
#: What of this project's interface a system uses, in the order of the matrix.
CAPABILITIES = {
    "allow_deny": "Allows and denies",
    "asks_a_person": "Asks a person",
    "abstains": "Abstains",
    "reason_codes": "Says why in a word",
    "reads_premises": "Reads the premises",
    "authority_from_record": "Works out who may act from the record",
    "verifies_mandates": "Verifies signed mandates",
    "verifies_readings": "Verifies signed readings",
    "states_findings": "States its own finding",
    "signs_receipts": "Signs its receipts",
    "keeps_state": "Keeps state between requests",
    "executes_itself": "Authorizes execution itself",
}
#: How far a system uses one of them. A difference is written down as carefully as a match.
USES = {"uses": "yes", "partial": "partly", "not_used": "no"}


def _problems(entry: Mapping[str, Any], name: str, repo: Path) -> list[str]:
    out = []
    enrolled = entry.get("enrolled")
    if not isinstance(enrolled, Mapping) or not ISSUE.fullmatch(str(enrolled.get("issue", ""))):
        out.append(f"{name}: enrolled.issue must be the registration issue in this repository")
    elif enrolled.get("listing_consent") is not True:
        out.append(f"{name}: enrolled.listing_consent must be true: no consent, no name")
    if entry.get("id") != name:
        out.append(f"{name}: id must be the file name")
    for key in ("name", "gate", "version"):
        if not str(entry.get(key) or "").strip():
            out.append(f"{name}: {key} is required")
    if entry.get("relation") not in RELATIONS:
        out.append(f"{name}: relation must be one of {', '.join(RELATIONS)}")
    if entry.get("connection") not in CONNECTIONS:
        out.append(f"{name}: connection must be one of {', '.join(CONNECTIONS)}")
    brings = entry.get("provides")
    if not isinstance(brings, list) or not brings or not set(brings) <= set(PROVIDES):
        out.append(f"{name}: provides must list one or more of {', '.join(PROVIDES)}")
    stated = entry.get("capabilities") or {}
    if not isinstance(stated, Mapping) or not set(stated) <= set(CAPABILITIES):
        out.append(f"{name}: capabilities may name only {', '.join(CAPABILITIES)}")
    elif not set(stated.values()) <= set(USES):
        out.append(f"{name}: a capability is one of {', '.join(USES)}")
    for result in entry.get("results") or []:
        if result.get("kind") not in KINDS:
            out.append(f"{name}: a result's kind must be one of {', '.join(KINDS)}")
        card = repo / str(result.get("card", ""))
        if not card.is_file():
            out.append(f"{name}: no card at {result.get('card')}")
    for finding in entry.get("findings") or []:
        if finding.get("status") not in STATUSES:
            out.append(f"{name}: a finding's status must be one of {', '.join(STATUSES)}")
        if finding.get("status") != "reported_privately" and not finding.get("disclosed"):
            out.append(f"{name}: finding {finding.get('id')} is published without a disclosed date")
    return out


def load(entries: Path = ENTRIES, repo: Path = REPO) -> tuple[list[dict[str, Any]], list[str]]:
    """Return the entries, by id, and what is wrong with them."""
    found, problems = [], []
    for path in sorted(entries.glob("*.yaml")):
        entry = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        problems += _problems(entry, path.stem, repo)
        found.append(entry)
    return found, problems


def _pct(value: Any) -> str:
    return "n/a" if value is None else f"{100.0 * float(value):.0f} %"


def _figure(row: Mapping[str, Any], key: str) -> str:
    if key == "approvals_per_24h":
        return f"{float(row.get(key) or 0):.1f}"
    return _pct(row.get(key))


def render(entries: Sequence[Mapping[str, Any]], repo: Path = REPO) -> str:
    """Return the page."""
    lines = [
        "<!-- Generated by tools/participants.py from docs/bench/participants/. Do not edit. -->",
        "",
        "# Enrolled systems",
        "",
        "A system is listed here only after its maintainers enrolled it themselves, with the "
        "[registration form](https://github.com/agentic-datacenter/agentic-datacenter/issues/new"
        "?template=gate-registration.yml), and agreed to be listed by name. Each row links that "
        "registration. Every system is listed under the same rules, in the order of its name. "
        "`relation` says whether its maintainers are independent of this project or are among "
        "its authors (`benchmark_authors`). Being listed is not an endorsement, by this project "
        "of the system or by the system of this project.",
        "",
        "## Results",
        "",
        "The figures are from each system's latest card, beside the two reference controls that "
        "ran on the same card, no control and limits only: the same scenarios, agents, seeds and "
        "judge.",
        "",
    ]
    if not entries:
        lines += ["No system has enrolled yet.", ""]
    else:
        lines += [
            "| System | Relation | Connected as | Version | Card | Agent | "
            + " | ".join(t for _, t in FIGURES)
            + " |",
            "| --- | --- | --- | --- | --- | --- |" + " ---: |" * len(FIGURES),
        ]
        for entry in entries:
            results = entry.get("results") or []
            name = f"[{entry['name']}]({entry['enrolled']['issue']})"
            head = f"| {name} | {entry['relation']} | {entry['connection']} | `{entry['version']}`"
            if not results:
                lines.append(head + " | no result yet | |" + " |" * len(FIGURES))
                continue
            latest = results[-1]
            card = json.loads((repo / latest["card"]).read_text(encoding="utf-8"))
            rows = [r for r in card["results"] if r["gate"] == entry["gate"]]
            beside = [r for r in card["results"] if r["gate"] in BUILT_IN]
            for row in rows + beside:
                who = (
                    head
                    if row in rows
                    else (f"| beside it: `{row['gate']}` (reference control) | | | ")
                )
                lines.append(
                    f"{who} | {latest['kind']}, {latest['agentic_datacenter']} | "
                    f"`{row['agent']}` | " + " | ".join(_figure(row, k) for k, _ in FIGURES) + " |"
                )
        lines.append("")
    lines += _matrix(entries)
    lines += ["## Findings", ""]
    published = [
        (e, f) for e in entries for f in e.get("findings") or []
        if f.get("status") != "reported_privately"
    ]  # fmt: skip
    private = sum(
        1 for e in entries for f in e.get("findings") or []
        if f.get("status") == "reported_privately"
    )  # fmt: skip
    lines += [
        "A finding is a weakness a run showed. It goes to the system's maintainers first, and is "
        "described here once they have fixed it or agreed to its publication. Until then it is "
        "counted and not described.",
        "",
        f"Reported to maintainers and not yet published: {private}.",
        "",
    ]
    if published:
        lines += [
            "| System | Finding | Scenario | Seen in | Status | Fixed in | Published |",
            "| --- | --- | --- | --- | --- | --- | --- |",
        ]
        for entry, f in published:
            lines.append(
                f"| {entry['name']} | {f.get('summary', '')} | {f.get('scenario', '')} | "
                f"{f.get('seen_in', '')} | {f['status']} | {f.get('fixed_in') or ''} | "
                f"{f.get('disclosed', '')} |"
            )
        lines.append("")
    return "\n".join(lines)


def _matrix(entries: Sequence[Mapping[str, Any]]) -> list[str]:
    """Return what each system brings, and what of the interface it uses, as two tables."""
    lines = [
        "## What each system brings",
        "",
        "A system need not decide anything to take part. It says what it brings:",
        "",
        *(f"- **{key}**: {text};" for key, text in PROVIDES.items()),
        "",
    ]
    if not entries:
        return [*lines, "No system has enrolled yet.", ""]
    lines += ["| System | Relation | Brings |", "| --- | --- | --- |"]
    for entry in entries:
        name = f"[{entry['name']}]({entry['enrolled']['issue']})"
        lines.append(f"| {name} | {entry['relation']} | {', '.join(entry['provides'])} |")
    lines += [
        "",
        "## What of the interface each system uses",
        "",
        "As each system's maintainers stated it in their entry. An empty cell was not stated. "
        'A "no" is as useful to a reader as a "yes": it says what a result of that system '
        "does not cover.",
        "",
        "| | " + " | ".join(entry["name"] for entry in entries) + " |",
        "| --- |" + " --- |" * len(entries),
    ]
    for key, title in CAPABILITIES.items():
        cells = [USES.get((entry.get("capabilities") or {}).get(key, ""), "") for entry in entries]
        lines.append(f"| {title} | " + " | ".join(cells) + " |")
    return [*lines, ""]


def main(argv: Sequence[str] | None = None) -> int:
    """Write the page, or check it and every entry."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    entries, problems = load()
    for problem in problems:
        print(problem, file=sys.stderr)
    if problems:
        return 1
    page = render(entries)
    if args.check:
        if not PAGE.is_file() or PAGE.read_text(encoding="utf-8") != page:
            print(f"{PAGE} is not up to date; run tools/participants.py", file=sys.stderr)
            return 1
        return 0
    PAGE.write_text(page, encoding="utf-8")
    print(f"written: {PAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
