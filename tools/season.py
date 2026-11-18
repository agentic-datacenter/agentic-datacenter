"""The seasons of the public test, from one rule (docs/bench/PUBLIC_TEST.md, ADR 0027).

Season 1 was set by hand. Every later season opens at the instant the one
before it closes and lasts four weeks, so a season is always open. Its
registration deadline is the instant its drand round is emitted, and the
round follows from the deadline, so every round is published long before it
exists. Nothing here is decided when a season ends; it is all in
``docs/bench/seasons.json``.

    python tools/season.py current                 # which season is open now
    python tools/season.py calendar --check        # the calendar on the page is the rule's
    python tools/season.py calendar --write        # after changing seasons.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "tools"))

from heldout_beacon import round_at  # noqa: E402

PLAN = REPO / "docs/bench/seasons.json"
PAGE = REPO / "docs/bench/PUBLIC_TEST.md"
START = "<!-- seasons: made by tools/season.py from docs/bench/seasons.json; do not edit -->"
END = "<!-- /seasons -->"


def load(path: Path = PLAN) -> dict[str, Any]:
    """Return the plan of the seasons."""
    return json.loads(path.read_text(encoding="utf-8"))  # type: ignore[no-any-return]


def _instant(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00"))


def _text(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _deadline(number: int, plan: Mapping[str, Any]) -> datetime:
    first = _instant(plan["first_deadline"])
    return first + timedelta(days=int(plan["length_days"]) * (number - 1))


def season(number: int, plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return season *number*: when it opens and closes, its round and its benchmark version."""
    if number < 1:
        raise ValueError("seasons are numbered from 1")
    plan = load() if plan is None else plan
    deadline = _deadline(number, plan)
    opens = plan["first_opened"] if number == 1 else _text(_deadline(number - 1, plan))
    versions = [v for v in plan["versions"] if int(v["from_season"]) <= number]
    return {
        "number": number,
        "opens": opens,
        "deadline": _text(deadline),
        "round": round_at(int(deadline.timestamp())),
        "version": max(versions, key=lambda v: int(v["from_season"]))["tag"],
    }


def current(at: datetime, plan: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Return the season open at *at*: the first whose deadline is still to come."""
    plan = load() if plan is None else plan
    number = 1
    while _deadline(number, plan) <= at:
        number += 1
    return season(number, plan)


def calendar(plan: Mapping[str, Any] | None = None) -> str:
    """Return the table of the seasons the plan lists."""
    plan = load() if plan is None else plan
    lines = [
        "| Season | Opens (UTC) | Registration closes and the round is emitted (UTC) "
        "| Beacon round | Benchmark version |",
        "| --- | --- | --- | --- | --- |",
    ]
    for number in range(1, int(plan["listed"]) + 1):
        s = season(number, plan)
        opens, closes = (
            t.replace("T", " ").replace(":00Z", "") for t in (s["opens"], s["deadline"])
        )
        lines.append(f"| {number} | {opens} | {closes} | `{s['round']}` | `{s['version']}` |")
    return "\n".join(lines)


def rendered(page: str, plan: Mapping[str, Any] | None = None) -> str:
    """Return *page* with the calendar between its two markers made anew."""
    before, _, rest = page.partition(START)
    _, found, after = rest.partition(END)
    if not found:
        raise ValueError(f"the page has no calendar between {START!r} and {END!r}")
    return f"{before}{START}\n{calendar(plan)}\n{END}{after}"


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    now = actions.add_parser("current", help="The season that is open.")
    now.add_argument("--at", help="ISO 8601; the present if left out.")
    table = actions.add_parser("calendar", help="The calendar on the public-test page.")
    how = table.add_mutually_exclusive_group()
    how.add_argument("--check", action="store_true", help="Fail if the page differs.")
    how.add_argument("--write", action="store_true", help="Write the calendar to the page.")
    args = parser.parse_args(argv)
    if args.action == "current":
        # The calendar, not simulator code: which season is open depends on today.
        at = _instant(args.at) if args.at else datetime.now(UTC)  # noqa: TID251
        s = current(at)
        left = _instant(s["deadline"]) - at
        print(
            f"Season {s['number']}: open since {s['opens']}, registration closes "
            f"{s['deadline']} (in {left.days} days), drand quicknet round {s['round']}, "
            f"benchmark version {s['version']}"
        )
        return 0
    page = PAGE.read_text(encoding="utf-8")
    made = rendered(page)
    if args.write:
        PAGE.write_text(made, encoding="utf-8")
    elif args.check and made != page:
        print("the calendar on the page is stale; run: python tools/season.py calendar --write")
        return 1
    else:
        print(calendar() if not args.check else "the calendar on the page is the rule's")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
