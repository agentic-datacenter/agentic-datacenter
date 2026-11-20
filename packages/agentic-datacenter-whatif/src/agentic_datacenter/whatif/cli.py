"""The ``agentic-datacenter whatif`` command: ``run``, ``policy`` and ``verify`` (ADR 0019)."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.evidence import code_commit
from agentic_datacenter.whatif.evidence import verify_whatif, write_policy, write_whatif
from agentic_datacenter.whatif.models import SpecError, WhatIfSpec, parse_spec
from agentic_datacenter.whatif.policy import run_policy
from agentic_datacenter.whatif.runner import run_whatif


def _spec(path: Path) -> WhatIfSpec:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SpecError(f"cannot read {path}: {exc}") from exc
    return parse_spec(data)


def _kwh(value: Any) -> str:
    return f"{float(value):,.1f} kWh"


def _report(summary: dict[str, Any]) -> None:
    preflight = summary["preflight"]
    print(
        f"preflight: {preflight['contract_id']} {preflight['start_value']:g} -> "
        f"{preflight['target']:g}: {preflight['verdict']}"
    )
    for name, branch in summary["branches"].items():
        if not branch["available"]:
            print(f"  {name:9s} not run: {branch['unavailable_reason']}")
            continue
        energy = branch["energy"]
        hottest = branch["physical"]["max_pod_c"]
        line = (
            f"  {name:9s} facility {_kwh(energy['facility_kwh'])}, PUE {energy['pue']:.4f}, "
            f"chillers {_kwh(energy['chiller_kwh'])}, hottest POD {hottest:.2f} C"
        )
        saving = summary["savings_against_baseline"].get(name)
        if saving is not None:
            line += (
                f", saves {_kwh(saving['facility_kwh_saved'])} "
                f"({saving['facility_saved_pct']:.2f} %)"
            )
        print(line)
        if branch.get("outcome"):
            outcome = branch["outcome"]
            print(
                f"            reached {outcome['final_value']:g} of {outcome['target']:g}; "
                f"stopped: {'; '.join(outcome['stopped_because'])}"
            )
    policy = summary["policy"]
    print(
        "policy analysis: "
        + ("available" if policy["available"] else f"not available ({policy['reason']})")
    )


def main(argv: Sequence[str]) -> int:
    """Play one proposed change as three branches, and check what-if evidence.

    Runs ``agentic-datacenter whatif ...`` and returns the exit status.
    The first line is the help text of ``agentic-datacenter --help``.
    """
    parser = argparse.ArgumentParser(
        prog="agentic-datacenter whatif", description="Play one proposed change as three branches."
    )
    actions = parser.add_subparsers(dest="action", required=True)
    for name, text in (
        ("run", "Play the branches and write the summary, series and evidence."),
        ("policy", "Write REMORA's policy analysis of the change only, as its own bundle."),
    ):
        action = actions.add_parser(name, help=text)
        action.add_argument("--spec", type=Path, required=True, help="The request, as JSON.")
        action.add_argument("--out", type=Path, required=True)
        action.add_argument("--profile", type=Path, default=Path("profiles/generic_dc.yaml"))
        action.add_argument("--contracts", type=Path, default=Path("contracts"))
    verify = actions.add_parser("verify", help="Check what-if evidence against its manifests.")
    verify.add_argument("directory", type=Path)
    args = parser.parse_args(list(argv))

    if args.action == "verify":
        problems = verify_whatif(args.directory)
        for problem in problems:
            print(problem, file=sys.stderr)
        print(f"{args.directory}: {'intact' if not problems else 'NOT intact'}")
        return 1 if problems else 0
    try:
        spec = _spec(args.spec)
        profile, contracts = load_profile(args.profile), ContractLibrary.load(args.contracts)
        commit = code_commit(Path.cwd())
        if args.action == "policy":
            policy = run_policy(spec, profile, contracts)
            write_policy(policy, spec, args.out, profile, contracts, commit)
            state = "available" if policy["available"] else f"not available: {policy['reason']}"
            print(f"policy analysis {state}; written to {args.out}")
            return 0
        result = run_whatif(
            spec, profile, contracts, progress=lambda line: print(f"  {line}", file=sys.stderr)
        )
    except SpecError as exc:
        print(f"agentic-datacenter whatif: {exc}", file=sys.stderr)
        return 2
    write_whatif(result, args.out, profile, contracts, commit)
    _report(result.summary())
    print(f"written to {args.out} (check with: agentic-datacenter whatif verify {args.out})")
    return 0
