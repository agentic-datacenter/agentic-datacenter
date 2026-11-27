"""The registry of operational findings: what runs have shown, and how far it holds.

    python tools/findings.py                       # writes docs/reference/findings.md
    python tools/findings.py --check               # all valid, page current, none stale
    python tools/findings.py search --scenario OP-03 --equipment <id> --gate <name>
    python tools/findings.py --dir <your private findings> --check

A finding is one claim a run supports, with the evidence it rests on, the
conditions it holds under, its limits, who replicated or contradicted it, and
what it replaces. It is a YAML file, ``findings/ADC-FIND-<nnnn>.yaml``,
validated here and in the tests.

Each finding records the hash of every input it depends on: scenarios,
equipment entries, the profile. When one of them changes, the finding is
*stale*: a finding that is ``supported`` or ``replicated`` must then be looked
at again, and ``--check`` says so. The repository holds public findings only.
A private one, about a site or a gate not yet published, is kept with the same
schema in a directory of its owner's, and checked with ``--dir``.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
FINDINGS = REPO / "findings"
PAGE = REPO / "docs/reference/findings.md"
ID = re.compile(r"ADC-FIND-\d{4}")
STATUSES = ("hypothesis", "supported", "replicated", "contradicted", "superseded")
#: Statuses whose claim rests on its evidence as it was: a change of an input matters.
SETTLED = ("supported", "replicated")
REQUIRED = (
    "finding_id", "status", "visibility", "claim", "scenarios", "facility_class",
    "evidence_refs", "depends_on", "validity_conditions", "limitations", "credited_to",
)  # fmt: skip


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def current_hashes(repo: Path = REPO) -> dict[str, dict[str, str]]:
    """Return the hash of every input a finding may depend on, as the repository holds it now."""
    from agentic_datacenter.core.profile import load_profile
    from agentic_datacenter.scenarios.scenario import library_ids, load_scenario

    equipment = {
        path.stem: _sha256(path)
        for path in sorted((repo / "equipment").glob("*/*.yaml"))
        if not path.name.startswith("TEMPLATE")
    }
    return {
        "scenarios": {s: load_scenario(s).hash() for s in library_ids()},
        "equipment": equipment,
        "profiles": {
            path.stem: load_profile(path).hash()
            for path in sorted((repo / "profiles").glob("*.yaml"))
            if path.stem != "restricted_ref"
        },
    }  # fmt: skip


def problems(finding: Mapping[str, Any], name: str, repo: Path) -> list[str]:
    """Return what is wrong with one finding."""
    out = [f"{name}: {key} is required" for key in REQUIRED if key not in finding]
    if out:
        return out
    if finding["finding_id"] != name or not ID.fullmatch(name):
        out.append(f"{name}: finding_id must be ADC-FIND-<nnnn> and the file's name")
    if finding["status"] not in STATUSES:
        out.append(f"{name}: status must be one of {', '.join(STATUSES)}")
    if finding["visibility"] != "public" and repo == REPO:
        out.append(f"{name}: only public findings are kept in this repository")
    if finding["status"] in SETTLED and not finding["evidence_refs"]:
        out.append(f"{name}: a {finding['status']} finding needs evidence")
    if finding["status"] == "replicated" and not finding.get("independent_replications"):
        out.append(f"{name}: a replicated finding names its independent replications")
    if finding["status"] == "superseded" and not finding.get("superseded_by"):
        out.append(f"{name}: a superseded finding names what superseded it")
    for ref in finding["evidence_refs"]:
        path = repo / str(ref.get("path", ""))
        if not path.is_file():
            out.append(f"{name}: no evidence at {ref.get('path')}")
        elif _sha256(path) != ref.get("sha256"):
            out.append(f"{name}: {ref.get('path')} does not match its sha256")
    for replication in finding.get("independent_replications") or []:
        if replication.get("result") not in ("confirms", "contradicts"):
            out.append(f"{name}: a replication's result is confirms or contradicts")
    if not finding["credited_to"]:
        out.append(f"{name}: credit at least one contributor, by the name they agreed to")
    return out


def stale(finding: Mapping[str, Any], now: Mapping[str, Mapping[str, str]]) -> list[str]:
    """Return the inputs of *finding* whose hash is no longer the one it recorded."""
    changed = []
    for kind, recorded in (finding.get("depends_on") or {}).items():
        for key, digest in (recorded or {}).items():
            if now.get(kind, {}).get(key) != digest:
                changed.append(f"{kind}/{key}")
    return changed


def load(directory: Path = FINDINGS) -> list[dict[str, Any]]:
    """Return the findings in *directory*, by id."""
    return [
        yaml.safe_load(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("ADC-FIND-*.yaml"))
    ]


def search(
    findings: Sequence[Mapping[str, Any]],
    scenario: str | None = None,
    equipment: str | None = None,
    gate: str | None = None,
    facility_class: str | None = None,
) -> list[Mapping[str, Any]]:
    """Return the findings that match every criterion given."""
    out = []
    for f in findings:
        if scenario and scenario not in f.get("scenarios", []):
            continue
        if equipment and equipment not in (f.get("depends_on", {}).get("equipment") or {}):
            continue
        if gate and gate not in (f.get("gates") or []):
            continue
        if facility_class and f.get("facility_class") != facility_class:
            continue
        out.append(f)
    return out


def render(findings: Sequence[Mapping[str, Any]], now: Mapping[str, Any]) -> str:
    """Return the page of public findings."""
    lines = [
        "<!-- Generated by tools/findings.py from findings/. Do not edit. -->",
        "",
        "# Operational findings",
        "",
        "What runs have shown, each claim with its evidence, the conditions it holds under, its "
        "limits, and who replicated or contradicted it. A finding is *stale* when an input it "
        "depends on has changed since it was recorded, and is then looked at again. Add one, or "
        "a replication of one, as described in "
        "[`findings/README.md`](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/findings/README.md).",
        "",
    ]
    if not findings:
        return "\n".join([*lines, "No finding is recorded yet.", ""])
    lines += [
        "| Finding | Status | Scenarios | Claim | Replications | Stale |",
        "| --- | --- | --- | --- | ---: | --- |",
    ]
    for f in findings:
        changed = stale(f, now)
        lines.append(
            f"| {f['finding_id']} | {f['status']} | {', '.join(f['scenarios'])} | "
            f"{' '.join(str(f['claim']).split())} | "
            f"{len(f.get('independent_replications') or [])} | "
            f"{', '.join(changed) if changed else 'no'} |"
        )
    lines.append("")
    for f in findings:
        lines += [
            f"## {f['finding_id']}",
            "",
            " ".join(str(f["claim"]).split()),
            "",
            f"- **Status:** {f['status']}. **Facility class:** {f['facility_class']}. "
            f"**Credited to:** {', '.join(f['credited_to'])}.",
            *[f"- **Holds when:** {c}" for c in f["validity_conditions"]],
            *[f"- **Limit:** {c}" for c in f["limitations"]],
            *[f"- **Evidence:** `{r['path']}` (sha256 `{r['sha256'][:12]}…`)"
              for r in f["evidence_refs"]],
            "",
        ]  # fmt: skip
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Write or check the page, or search the findings."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("action", nargs="?", choices=["search"])
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--dir", type=Path, default=FINDINGS)
    for option in ("scenario", "equipment", "gate", "facility-class"):
        parser.add_argument(f"--{option}")
    args = parser.parse_args(argv)
    repo = REPO if args.dir == FINDINGS else args.dir
    findings = load(args.dir)
    if args.action == "search":
        for f in search(findings, args.scenario, args.equipment, args.gate, args.facility_class):
            print(f"{f['finding_id']} [{f['status']}] {' '.join(str(f['claim']).split())}")
        return 0
    errors = [p for f in findings for p in problems(f, str(f.get("finding_id")), repo)]
    now = current_hashes()
    for f in findings:
        changed = stale(f, now)
        if changed and f.get("status") in SETTLED:
            errors.append(
                f"{f['finding_id']}: {f['status']} but stale: {', '.join(changed)} changed since; "
                "look at it again and record the new hashes, or change its status"
            )
    for error in errors:
        print(error, file=sys.stderr)
    if errors:
        return 1
    if args.dir != FINDINGS:
        print(f"{len(findings)} finding(s) valid")
        return 0
    page = render(findings, now)
    if args.check:
        if not PAGE.is_file() or PAGE.read_text(encoding="utf-8") != page:
            print(f"{PAGE} is not up to date; run tools/findings.py", file=sys.stderr)
            return 1
        return 0
    PAGE.write_text(page, encoding="utf-8")
    print(f"written: {PAGE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
