"""Write the scenario-matrix metric difference between two REMORA pins (ADC-PIN-004).

A pin bump changes the pin and the lock and nothing else, so the same benchmark
run at the previous pin and at the new one shows what the bump does. This tool
reads the two result cards and the two ``REMORA_PIN`` files and writes the
difference as Markdown: every figure of every gate and agent at both pins, the
invariant breaches and harmful executions at both pins, and the runs whose
outcome changed.

It refuses two cards that are not the same benchmark (version, scenarios,
seeds, agents, judging), and two pins that are the same commit. It returns 1
when the new pin has more of any invariant breach or harmful execution than
the previous one: such a bump is blocked (SDD 5.2).

The cards do not record the REMORA commit they were made with. The caller
vouches for that: ``.github/workflows/pin-bump.yml`` runs ``tools/check_pin.py``
in each tree before it makes the card there.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agentic_datacenter.scenarios.release_gate import BREACHES

#: What two cards must share for their figures to be comparable.
SAME = (
    "schema_version", "benchmark_version", "judging", "seeds", "agents", "scenarios",
    "duration_override_s", "counterfactual", "heldout",
)  # fmt: skip
#: The judgement that marks an executed step the replay found harmful.
HARMFUL = "unsafe_execution"


class PinDiffError(ValueError):
    """The two cards or the two pins cannot be compared."""


def pin(text: str) -> tuple[str, str]:
    """Return the tag and the commit recorded in the text of a ``REMORA_PIN`` file."""
    commit = re.search(r"^commit:\s*([0-9a-f]{40})\s*$", text, re.M)
    tag = re.search(r"^tag:\s*(\S+)\s*$", text, re.M)
    if commit is None or tag is None:
        raise PinDiffError("a REMORA_PIN file needs a tag line and a 40-character commit line")
    return tag.group(1), commit.group(1)


def comparable(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """Return why the two cards are not the same benchmark; nothing if they are."""
    problems = [
        f"the cards differ in {key}: {old.get(key)!r} and {new.get(key)!r}"
        for key in SAME
        if old.get(key) != new.get(key)
    ]
    rows_old, rows_new = (
        {(r["gate"], r["agent"]) for r in card.get("results", [])} for card in (old, new)
    )
    if rows_old != rows_new:
        problems.append(f"the cards differ in gates and agents: {rows_old ^ rows_new}")
    runs_old, runs_new = ({r["run_id"] for r in card.get("runs", [])} for card in (old, new))
    if runs_old != runs_new:
        problems.append(f"the cards differ in runs: {sorted(runs_old ^ runs_new)}")
    if not rows_old or not runs_old:
        problems.append("the previous card has no results or no runs")
    return problems


def breaches(card: Mapping[str, Any], gate: str) -> dict[str, float]:
    """Return every invariant breach and the harmful executions of *gate*, summed over its runs."""
    runs = [r for r in card["runs"] if r["gate"] == gate]
    out = {name: sum(float(r["metrics"][name]) for r in runs) for name in BREACHES}
    out[HARMFUL] = float(sum(int(r["kinds"].get(HARMFUL, 0)) for r in runs))
    return out


def regressions(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """Return every breach the new pin has more of than the previous one."""
    found = []
    for gate in dict.fromkeys(r["gate"] for r in new["results"]):
        before, after = breaches(old, gate), breaches(new, gate)
        for name, value in after.items():
            if value > before[name]:
                meaning = BREACHES.get(name, "an executed step the replay found harmful")
                found.append(f"{gate}: {name} rose from {before[name]:g} to {value:g} ({meaning})")
    return found


def _number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _show(value: object) -> str:
    if value is None:
        return "none"
    return f"{value:.6g}" if isinstance(value, float) else str(value)


def _change(before: object, after: object) -> str:
    if before == after:
        return "same"
    if _number(before) and _number(after):
        return f"{float(after) - float(before):+.6g}"  # type: ignore[arg-type]
    return "changed"


def changed_runs(old: Mapping[str, Any], new: Mapping[str, Any]) -> list[str]:
    """Return one line for every run whose result, judgements or final state changed."""
    before = {r["run_id"]: r for r in old["runs"]}
    lines = []
    for run in new["runs"]:
        was = before[run["run_id"]]
        what = [
            name
            for name, key in (
                ("passed", "passed"), ("failed criteria", "failed_criteria"),
                ("judgements", "kinds"), ("metrics", "metrics"),
                ("final state", "final_state_hash"),
            )
            if was.get(key) != run.get(key)
        ]  # fmt: skip
        if what:
            lines.append(f"`{run['run_id']}`: {', '.join(what)}")
    return lines


def render(
    old: Mapping[str, Any],
    new: Mapping[str, Any],
    old_pin: tuple[str, str],
    new_pin: tuple[str, str],
) -> str:
    """Return the metric difference of two comparable cards as Markdown."""
    blocked = regressions(old, new)
    judging = new["judging"]
    shortened = new.get("duration_override_s")
    length = f"each scenario shortened to {shortened} s" if shortened else "at full length"
    lines = [
        "<!-- Generated by tools/pin_diff.py from two result cards. Do not edit. -->",
        "",
        "# Metric difference of a REMORA pin bump",
        "",
        f"- Previous pin: `{old_pin[0]}`, commit `{old_pin[1]}`",
        f"- New pin: `{new_pin[0]}`, commit `{new_pin[1]}`",
        f"- Benchmark: {len(new['scenarios'])} scenarios, seeds {new['seeds']}, {length}",
        f"- Judging: horizon {judging.get('horizon_s')} s, at most {judging.get('max_judged')} "
        "proposals per run",
        f"- {new['label']}. These are simulation results, made to compare two pins and "
        "nothing else.",
        "",
        "## Invariant breaches and harmful executions",
        "",
        "More of any of these at the new pin blocks the bump.",
        "",
        "| Gate | Count | Previous pin | New pin | Change |",
        "| --- | --- | --- | --- | --- |",
    ]
    for gate in dict.fromkeys(r["gate"] for r in new["results"]):
        before, after = breaches(old, gate), breaches(new, gate)
        lines += [
            f"| `{gate}` | `{name}` | {_show(before[name])} | {_show(after[name])} "
            f"| {_change(before[name], after[name])} |"
            for name in after
        ]
    lines += ["", f"Result: {'BLOCKED' if blocked else 'no regression'}.", ""]
    lines += [f"- {line}" for line in blocked] + ([""] if blocked else [])
    lines += ["## Figures of each gate and agent", ""]
    rows_old = {(r["gate"], r["agent"]): r for r in old["results"]}
    for row in new["results"]:
        was = rows_old[(row["gate"], row["agent"])]
        lines += [
            f"### `{row['gate']}` with `{row['agent']}` ({row['operating_profile']})",
            "",
            "| Figure | Previous pin | New pin | Change |",
            "| --- | --- | --- | --- |",
        ]
        for name in sorted(set(was) | set(row)):
            before, after = was.get(name), row.get(name)
            if _number(before) or _number(after) or before is None and after is None:
                lines.append(
                    f"| `{name}` | {_show(before)} | {_show(after)} | {_change(before, after)} |"
                )
        lines.append("")
    runs = changed_runs(old, new)
    lines += [f"## Runs that changed: {len(runs)} of {len(new['runs'])}", ""]
    lines += [f"- {line}" for line in runs] or ["None. Every run gave the same result."]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Write the difference; 2 when it cannot be made, 1 when it blocks the bump."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--old-card", type=Path, required=True, help="Card made at the old pin.")
    parser.add_argument("--old-pin", type=Path, required=True, help="REMORA_PIN of the old pin.")
    parser.add_argument("--new-card", type=Path, required=True, help="Card made at the new pin.")
    parser.add_argument("--new-pin", type=Path, default=Path("REMORA_PIN"))
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        old_pin = pin(args.old_pin.read_text(encoding="utf-8"))
        new_pin = pin(args.new_pin.read_text(encoding="utf-8"))
        if old_pin[1] == new_pin[1]:
            raise PinDiffError(f"both pins are commit {new_pin[1]}; there is nothing to compare")
        old = json.loads(args.old_card.read_text(encoding="utf-8"))
        new = json.loads(args.new_card.read_text(encoding="utf-8"))
        problems = comparable(old, new)
        if problems:
            raise PinDiffError("; ".join(problems))
    except (OSError, ValueError) as exc:
        print(f"pin_diff: {exc}", file=sys.stderr)
        return 2
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(old, new, old_pin, new_pin), encoding="utf-8")
    blocked = regressions(old, new)
    for line in blocked:
        print(f"BLOCKED: {line}", file=sys.stderr)
    print(f"wrote {args.out}")
    return 1 if blocked else 0


if __name__ == "__main__":
    sys.exit(main())
