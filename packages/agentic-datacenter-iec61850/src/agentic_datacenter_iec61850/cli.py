"""The ``agentic-datacenter scl`` command: write the engineering files of a profile (SDD 8.5)."""

from __future__ import annotations

import argparse
from collections.abc import Sequence
from pathlib import Path

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.supervisory.points import PointDatabase
from agentic_datacenter_iec61850 import scl
from agentic_datacenter_iec61850.model import relays


def main(argv: Sequence[str]) -> int:
    """Run ``agentic-datacenter scl`` with *argv* and return its exit status."""
    parser = argparse.ArgumentParser(
        prog="agentic-datacenter scl", description="IEC 61850 engineering files."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    export = actions.add_parser("export", help="Write one SCD and one ICD per relay type.")
    export.add_argument("--profile", type=Path, required=True, help="Facility profile.")
    export.add_argument("--out", type=Path, required=True, help="Directory to write into.")
    arguments = parser.parse_args(list(argv))
    # The files depend on the profile only; the seed plays no part.
    kernel = Kernel(seed=0)
    plant = build_plant(load_profile(arguments.profile), kernel, ModuleRegistry.from_entry_points())
    for path in scl.export(relays(PointDatabase(kernel, plant)), arguments.out):
        print(path)
    return 0
