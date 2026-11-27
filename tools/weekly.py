"""The weekly scenario: sealed before it is shown, released on a Monday (ADR 0046).

A scenario for a coming week is written and tried, and the SHA-256 of its file
goes into ``weekly/register.yaml`` at least three days before its Monday. The
file itself is kept back. On the Monday it is put into ``weekly/scenarios/``,
and anyone can see that it is the file that was sealed.

Usage::

    python tools/weekly.py check                       # the register and the files agree
    python tools/weekly.py seal FILE --release-on DATE # print the entry to add
    python tools/weekly.py release FILE                # put a sealed file in place
    python tools/weekly.py due [--today DATE]          # what is late, and what is missing

``check`` and ``due`` exit with status 1 when something is wrong or missing.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
REGISTER = REPO / "weekly/register.yaml"
SCENARIOS = REPO / "weekly/scenarios"
SCHEMA = "agentic_datacenter.weekly/1"
STATUSES = ("planned", "sealed", "released", "withdrawn")
#: A file is sealed at least this many days before the Monday it is released on.
SEALED_DAYS_BEFORE = 3
MONDAY = 0
#: A weekly scenario is short: something a maintainer runs in under a minute for each
#: control, and can reason about. Nothing that plays out over a day.
MAX_DURATION_S = 7200
HEADER = """\
# The weekly scenarios: one for each Monday (docs/bench/WEEKLY.md, ADR 0046).
#
# planned    a week has a scenario in the making; nothing is sealed yet
# sealed     the SHA-256 of its file is here; the file is kept back until its Monday
# released   the file is in weekly/scenarios/ and hashes to what was sealed
# withdrawn  it will not be released, and `note` says why
#
# An entry is added with `python tools/weekly.py seal`, and never changed after
# it is sealed, but for its status. `python tools/weekly.py check` holds the
# files to this register.
"""


def _today() -> date:
    """Return the day on the wall clock: a week is a week of the calendar, not of a simulation."""
    return date.today()  # noqa: TID251


def digest(path: Path) -> str:
    """Return the SHA-256 of a file's bytes, in hex."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(register: Path = REGISTER) -> dict[str, Any]:
    """Read the register."""
    data = yaml.safe_load(register.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{register} is not a mapping")
    return data


def save(data: dict[str, Any], register: Path = REGISTER) -> None:
    """Write the register, with its header."""
    body = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=100)
    register.write_text(HEADER + body, encoding="utf-8")


def _day(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except ValueError:
        return None


def problems(data: dict[str, Any], scenarios: Path = SCENARIOS) -> list[str]:
    """Return what is wrong with the register and the released files; empty when all is well."""
    found: list[str] = []
    if data.get("schema") != SCHEMA:
        found.append(f"schema must be {SCHEMA}")
    entries = data.get("entries")
    if not isinstance(entries, list):
        return [*found, "entries must be a list"]
    seen_ids: set[str] = set()
    seen_weeks: set[tuple[int, int]] = set()
    for number, entry in enumerate(entries, start=1):
        name = str(entry.get("id"))
        if name != f"WK-{number:02d}":
            found.append(f"entry {number} must have the id WK-{number:02d}, not {name}")
        if name in seen_ids:
            found.append(f"{name} is listed twice")
        seen_ids.add(name)
        status = entry.get("status")
        if status not in STATUSES:
            found.append(f"{name}: status must be one of {', '.join(STATUSES)}")
        released_on = _day(entry.get("release_on"))
        if released_on is None or released_on.weekday() != MONDAY:
            found.append(f"{name}: release_on must be a Monday")
        elif status != "withdrawn":
            week = released_on.isocalendar()[:2]
            if week in seen_weeks:
                found.append(f"{name}: its week already has a scenario")
            seen_weeks.add(week)
        for key in ("family", "proposer"):
            if not isinstance(entry.get(key), str) or not entry[key].strip():
                found.append(f"{name}: {key} must be text")
        if status == "withdrawn" and not entry.get("note"):
            found.append(f"{name}: a withdrawn scenario says why, in note")
        file = scenarios / f"{name}.yaml"
        sealed = entry.get("sha256")
        if status == "planned":
            if sealed is not None:
                found.append(f"{name}: a planned scenario has no hash yet")
        elif status in ("sealed", "released"):
            if not isinstance(sealed, str) or not re.fullmatch(r"[0-9a-f]{64}", sealed):
                found.append(f"{name}: sha256 must be 64 hex digits")
            sealed_on = _day(entry.get("sealed_on"))
            if sealed_on is None:
                found.append(f"{name}: sealed_on must be a date")
            elif released_on and sealed_on > released_on - timedelta(days=SEALED_DAYS_BEFORE):
                found.append(
                    f"{name}: sealed on {sealed_on}, less than {SEALED_DAYS_BEFORE} days before"
                    f" its release on {released_on}"
                )
        if status == "released":
            if not file.is_file():
                found.append(
                    f"{name}: released, and {file.relative_to(scenarios.parent)} is missing"
                )
            elif digest(file) != sealed:
                found.append(f"{name}: the file is not the one that was sealed")
            else:
                loaded = yaml.safe_load(file.read_text(encoding="utf-8"))
                if not isinstance(loaded, dict) or loaded.get("id") != name:
                    found.append(f"{name}: the file's own id is not {name}")
                elif too_long(loaded):
                    found.append(f"{name}: {too_long(loaded)}")
        elif file.exists():
            found.append(f"{name}: its file is in the repository, and it is {status}, not released")
    for file in sorted(scenarios.glob("*.yaml")) if scenarios.is_dir() else ():
        if file.stem not in seen_ids:
            found.append(f"{file.name} is in weekly/scenarios/ with no entry in the register")
    return found


def too_long(scenario: dict[str, Any]) -> str:
    """Return why a scenario is too long for a week, or the empty string."""
    seconds = scenario.get("duration_s")
    if not isinstance(seconds, int) or seconds > MAX_DURATION_S:
        return (
            f"a weekly scenario lasts at most {MAX_DURATION_S // 3600} simulated hours,"
            f" and this one lasts {seconds} s"
        )
    return ""


def due(data: dict[str, Any], today: date) -> list[str]:
    """Return what needs a person: a late release, or a coming Monday with nothing sealed."""
    found = []
    entries = [e for e in data.get("entries", []) if e.get("status") != "withdrawn"]
    by_day = {_day(e.get("release_on")): e for e in entries}
    for entry in entries:
        day = _day(entry.get("release_on"))
        if day and day <= today and entry["status"] != "released":
            found.append(
                f"{entry['id']} was to be released on {day} and is {entry['status']}:"
                " run `python tools/weekly.py release <its file>` and open a pull request"
            )
    following = today + timedelta(days=(MONDAY - today.weekday()) % 7 or 7)
    coming = by_day.get(following)
    if coming is None:
        found.append(f"no scenario is in the register for Monday {following}")
    elif coming["status"] == "planned":
        last = following - timedelta(days=SEALED_DAYS_BEFORE)
        late = " That day has passed: move it a week." if today > last else ""
        found.append(
            f"{coming['id']} for Monday {following} is planned and not sealed;"
            f" it must be sealed by {last}.{late}"
        )
    return found


def entry_for(
    file: Path, release_on: date, today: date, number: int, **fields: str
) -> dict[str, Any]:
    """Return the register entry that seals *file* for *release_on*."""
    loaded = yaml.safe_load(file.read_text(encoding="utf-8"))
    name = f"WK-{number:02d}"
    if not isinstance(loaded, dict) or loaded.get("id") != name:
        raise ValueError(f"the file's own id must be {name}, the next in the register")
    if too_long(loaded):
        raise ValueError(too_long(loaded))
    return {
        "id": name,
        "release_on": release_on.isoformat(),
        "status": "sealed",
        "sealed_on": today.isoformat(),
        "sha256": digest(file),
        **fields,
    }


def main(argv: Sequence[str] | None = None) -> int:
    """Run one of the four actions and return the exit status."""
    parser = argparse.ArgumentParser(description="The weekly scenario (ADR 0046).")
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("check", help="Check the register against the released files.")
    seal = actions.add_parser("seal", help="Seal a scenario file for a coming Monday.")
    seal.add_argument("file", type=Path)
    seal.add_argument("--release-on", required=True, type=date.fromisoformat)
    seal.add_argument("--family", required=True, help="authority, plant, grid, evidence, ...")
    seal.add_argument("--proposer", default="project", help="A GitHub account, or `project`.")
    seal.add_argument("--issue", type=int, help="The issue it was proposed in, if any.")
    seal.add_argument("--today", type=date.fromisoformat, default=_today())
    seal.add_argument("--write", action="store_true", help="Add the entry to the register.")
    release = actions.add_parser("release", help="Put a sealed file into weekly/scenarios/.")
    release.add_argument("file", type=Path)
    late = actions.add_parser("due", help="Say what is late and what is missing.")
    late.add_argument("--today", type=date.fromisoformat, default=_today())
    args = parser.parse_args(argv)
    data = load()

    if args.action == "check":
        found = problems(data)
    elif args.action == "due":
        found = due(data, args.today)
    elif args.action == "seal":
        planned = [e for e in data["entries"] if e["release_on"] == args.release_on.isoformat()]
        number = int(planned[0]["id"][3:]) if planned else len(data["entries"]) + 1
        fields = {"family": args.family, "proposer": args.proposer}
        entry = entry_for(args.file, args.release_on, args.today, number, **fields)
        if args.issue is not None:
            entry["issue"] = args.issue
        if planned:
            data["entries"][number - 1] = entry
        else:
            data["entries"].append(entry)
        found = problems(data)
        if not found and args.write:
            save(data)
        print(yaml.safe_dump([entry], sort_keys=False).rstrip())
    else:
        loaded = yaml.safe_load(args.file.read_text(encoding="utf-8"))
        match = [e for e in data["entries"] if e["id"] == (loaded or {}).get("id")]
        if not match or match[0]["status"] != "sealed":
            found = [f"{args.file} is not a sealed scenario of the register"]
        elif digest(args.file) != match[0]["sha256"]:
            found = [f"{args.file} is not the file that was sealed as {match[0]['id']}"]
        else:
            SCENARIOS.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(args.file, SCENARIOS / f"{match[0]['id']}.yaml")
            match[0]["status"] = "released"
            found = problems(data)
            if not found:
                save(data)
                print(f"{match[0]['id']} is released: weekly/scenarios/{match[0]['id']}.yaml")
    for line in found:
        print(line, file=sys.stderr)
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
