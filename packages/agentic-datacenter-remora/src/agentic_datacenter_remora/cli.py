"""The ``agentic-datacenter contracts`` command."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

from agentic_datacenter.governance.contracts import ContractError, ContractLibrary
from agentic_datacenter_remora.compile import CompileError, compile_contracts


def contracts(argv: Sequence[str]) -> int:
    """Compile the intent contracts to the signed artifacts REMORA loads.

    Runs ``agentic-datacenter contracts compile`` and returns the exit status.
    The first line is the help text of ``agentic-datacenter --help``.
    """
    parser = argparse.ArgumentParser(
        prog="agentic-datacenter contracts", description="Intent contracts."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    build = actions.add_parser(
        "compile", help="Compile the contracts to the signed artifacts REMORA loads."
    )
    build.add_argument("--contracts", type=Path, default=Path("contracts"))
    build.add_argument("--out", type=Path, default=Path("build/contracts"))
    args = parser.parse_args(argv)
    try:
        compiled = compile_contracts(ContractLibrary.load(args.contracts), args.out)
    except (ContractError, CompileError) as exc:
        print(f"agentic-datacenter contracts: {exc}", file=sys.stderr)
        return 1
    manifest = compiled.manifest
    print(f"{manifest['label']}: {len(manifest['tools'])} contract(s) compiled to {args.out}")
    for name, digest in sorted(manifest["sha256"].items()):
        print(f"  {name}  sha256 {digest}")
    return 0
