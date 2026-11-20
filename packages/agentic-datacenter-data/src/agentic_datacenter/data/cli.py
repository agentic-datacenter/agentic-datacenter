"""The ``agentic-datacenter data`` command: write and check a dataset manifest."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path

from agentic_datacenter.data.errors import MeasuredSeriesError
from agentic_datacenter.data.series import format_utc, load_series, parse_utc_ms, write_manifest


def _units(pairs: Sequence[str]) -> dict[str, str]:
    units = {}
    for pair in pairs:
        column, sep, unit = pair.partition("=")
        if not sep or not column or not unit:
            raise SystemExit(f"agentic-datacenter data: --unit takes COLUMN=UNIT, got {pair!r}")
        units[column] = unit
    return units


def main(argv: Sequence[str]) -> int:
    """Write and check the manifest of a measured input series.

    Runs ``agentic-datacenter data manifest|check`` and returns the exit status.
    The first line is the help text of ``agentic-datacenter --help``.
    """
    parser = argparse.ArgumentParser(
        prog="agentic-datacenter data", description="Measured input series."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    make = actions.add_parser("manifest", help="Write dataset_manifest.json beside a series.")
    make.add_argument("series", type=Path, help="The series CSV in Agentic-Datacenter's format.")
    make.add_argument("--dataset-id", required=True)
    make.add_argument("--title", required=True)
    make.add_argument("--source", required=True, help="Where the data comes from.")
    make.add_argument("--version", required=True, help="Version or commit of the source.")
    make.add_argument("--doi")
    make.add_argument(
        "--licence", required=True, help="The licence exactly as the source states it."
    )
    make.add_argument("--redistribution", choices=["not_cleared", "cleared"], default="not_cleared")
    make.add_argument("--quality", required=True, help="Quality status, e.g. raw or cleaned.")
    make.add_argument("--unit", action="append", default=[], help="COLUMN=UNIT; repeat.")
    make.add_argument("--gap-tolerance-s", type=int, required=True)
    make.add_argument("--step-s", type=int, default=3600)
    make.add_argument("--derivation", default="", help="How the series was made from the source.")
    make.add_argument("--notes", default="")
    make.add_argument(
        "--extra", type=Path, action="append", default=[], help="Another file to hash."
    )
    check = actions.add_parser("check", help="Verify a dataset and print its provenance.")
    check.add_argument("manifest", type=Path)
    check.add_argument("--anchor-utc", help="Simulated t=0, to check a run window.")
    check.add_argument("--seconds", type=int, help="Length of the run window.")
    args = parser.parse_args(argv)

    try:
        if args.action == "manifest":
            out = write_manifest(
                args.series, dataset_id=args.dataset_id, title=args.title, source=args.source,
                version=args.version, doi=args.doi, licence=args.licence,
                redistribution=args.redistribution, quality_status=args.quality,
                units=_units(args.unit), gap_tolerance_s=args.gap_tolerance_s,
                step_s=args.step_s, derivation=args.derivation, notes=args.notes,
                extra_files=args.extra,
            )  # fmt: skip
            print(f"wrote {out}")
            return 0
        series = load_series(args.manifest)
        print(json.dumps(series.provenance(), indent=2, sort_keys=True))
        if args.anchor_utc is not None:
            start = parse_utc_ms(args.anchor_utc)
            end = start + 1000 * (args.seconds or 0)
            for column in series.columns:
                for t in range(start, end + 1, 1000 * series.manifest.step_s):
                    series.value_at(column, t)
                series.value_at(column, end)
            print(f"window {format_utc(start)} to {format_utc(end)}: covered")
        return 0
    except (MeasuredSeriesError, ValueError) as exc:
        print(f"agentic-datacenter data: {exc}", file=sys.stderr)
        return 1
