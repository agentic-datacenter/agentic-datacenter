"""Write the page of the weeks drawn so far, for the documentation site (ADR 0047).

The site is built again every Monday, and this runs before it: it asks the
beacon which week it is, draws every week from the first to this one, and
writes ``docs/bench/weekly-drawn.md`` with this week's three scenarios in full
and every earlier week in a table. Nothing is run; drawing takes no time.

    uv run python tools/weekly_page.py

If the beacon cannot be reached the page committed to the repository is left
as it is, so that a site is still published. The exit status is always 0.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from datetime import timedelta
from pathlib import Path
from typing import Any

from agentic_datacenter.scenarios import weekly

REPO = Path(__file__).resolve().parents[1]
PAGE = REPO / "docs/bench/weekly-drawn.md"
#: Earlier weeks listed on the page; older ones can be drawn again by anyone.
LISTED = 52

Drawn = tuple[str, int, list[dict[str, Any]]]


def weeks_until(last: str) -> list[str]:
    """Return every week from the first to *last*, oldest first; empty before the first."""
    try:
        end = weekly.monday_of(last)
    except weekly.WeeklyError:
        return []
    day, out = weekly.monday_of(weekly.FIRST_WEEK), []
    while day <= end:
        out.append(weekly.week_of(day))
        day += timedelta(days=7)
    return out


def draw_all(last: str, randomness: Callable[[int], str]) -> list[Drawn]:
    """Return every week to *last* with its round and its scenarios, newest first."""
    drawn = []
    for week in weeks_until(last):
        round_number = weekly.round_for(week)
        drawn.append((week, round_number, weekly.generate(week, randomness(round_number))))
    return drawn[::-1]


def render(drawn: Sequence[Drawn]) -> str:
    """Return the page for the weeks in *drawn*, newest first."""
    lines = [
        "# The weeks drawn so far",
        "",
        "Three scenarios are drawn for every week from a public randomness beacon, and nobody"
        " writes them ([how it works, and how to run them](WEEKLY.md)). This page is made again"
        " every Monday.",
        "",
    ]
    if not drawn:
        first = weekly.monday_of(weekly.FIRST_WEEK)
        return "\n".join(
            [
                *lines,
                f"The first week is drawn on Monday {first}, at 00:00 UTC. Until then there is"
                " nothing to show, and nobody knows what it will be.",
                "",
            ]
        )
    week, round_number, scenarios = drawn[0]
    lines += [
        f"## This week: {week}, from Monday {weekly.monday_of(week)}",
        "",
        f"Drawn by generator {weekly.GENERATOR} from round {round_number} of the drand quicknet"
        " beacon.",
        "",
        "```sh",
        f"uv run agentic-datacenter weekly run --week {week} --gate static_allowlist",
        "```",
        "",
    ]
    for one in scenarios:
        about = [line[2:] for line in one["text"].splitlines()[3:] if line.startswith("# ")]
        lines += [
            f"### `{one['id']}`: {one['scenario'].title}",
            "",
            " ".join(about),
            "",
            f"The file, of kind `{one['kind']}`:",
            "",
            "```yaml",
            *one["text"].splitlines(),
            "```",
            "",
        ]
    if len(drawn) > 1:
        lines += [
            "## Earlier weeks",
            "",
            "| Week | Monday | Beacon round | Drawn |",
            "| --- | --- | --- | --- |",
        ]
        for earlier, number, made in drawn[1 : LISTED + 1]:
            kinds = ", ".join(f"`{one['kind']}`" for one in made)
            lines.append(f"| {earlier} | {weekly.monday_of(earlier)} | {number} | {kinds} |")
        lines += [
            "",
            "Any of them can be drawn again: `uv run agentic-datacenter weekly show --week"
            " 2026-W49`.",
            "",
        ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Write the page, or leave it when the beacon cannot be reached."""
    del argv
    try:
        drawn = draw_all(weekly.this_week(), weekly.fetch_randomness)
    except weekly.WeeklyError as exc:
        print(f"the page is left as it is: {exc}", file=sys.stderr)
        return 0
    PAGE.write_text(render(drawn), encoding="utf-8")
    print(f"{PAGE.relative_to(REPO)}: {len(drawn)} weeks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
