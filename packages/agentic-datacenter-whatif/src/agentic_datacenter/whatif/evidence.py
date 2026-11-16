"""Evidence of a what-if (ADR 0019, decision 8).

Each branch that ran writes an evidence bundle in the format of
``agentic_datacenter.scenarios.evidence``, with its series, its description and, for the
governed branch, the agent's log added and listed in its manifest. A what-if
manifest at the top records the request, the versions, the REMORA commit of
each part that used REMORA, the start state hashes, and the hash of every file
below it, including each branch's manifest. ``agentic-datacenter scenario verify`` checks
any one of them; :func:`verify_whatif` checks them all.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.evidence import build_bundle, verify_bundle, write_bundle
from agentic_datacenter.whatif.models import WhatIfSpec, load_whatif_scenario
from agentic_datacenter.whatif.runner import WhatIfResult

SCHEMA_VERSION = 1
LETTERS = {"baseline": "A", "physical": "B", "governed": "C"}
DISTRIBUTIONS = (
    "agentic-datacenter-core", "agentic-datacenter-plant", "agentic-datacenter-supervisory",
    "agentic-datacenter-net", "agentic-datacenter-governance", "agentic-datacenter-scenarios",
    "agentic-datacenter-whatif", "agentic-datacenter-remora", "remora-assurance",
)  # fmt: skip


def _json(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True) + "\n"


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def versions() -> dict[str, str | None]:
    """Return the installed version of each distribution a what-if may use."""
    out: dict[str, str | None] = {}
    for name in DISTRIBUTIONS:
        try:
            out[name] = version(name)
        except PackageNotFoundError:
            out[name] = None
    return out


def contracts_hash(contracts: ContractLibrary) -> str:
    """Return the hash of the contract library, as an evidence bundle records it."""
    held = [contracts.get(i) for i in contracts.ids()]
    dumps = [c.model_dump(mode="json") for c in held if c is not None]
    return hashlib.sha256(json.dumps(dumps, sort_keys=True).encode()).hexdigest()


def _extend(
    bundle: Mapping[str, str], extra: Mapping[str, str], block: Mapping[str, Any]
) -> dict[str, str]:
    """Add *extra* files to a bundle, list them in its manifest and record *block* there."""
    manifest = json.loads(bundle["manifest.json"])
    manifest["files"].update({name: _sha(text) for name, text in extra.items()})
    manifest["whatif"] = dict(block)
    return {**bundle, **extra, "manifest.json": _json(manifest)}


def _top(directory: Path, files: Mapping[str, str], manifest: dict[str, Any]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (directory / name).write_text(text, encoding="utf-8")
    manifest["files"] = {
        **manifest.get("files", {}),
        **{name: _sha(text) for name, text in files.items()},
    }
    (directory / "manifest.json").write_text(_json(manifest), encoding="utf-8")
    return directory


def _common(
    spec: WhatIfSpec, profile: Profile, contracts: ContractLibrary, commit: str
) -> dict[str, Any]:
    scenario = load_whatif_scenario(spec.scenario)
    return {
        "schema_version": SCHEMA_VERSION,
        "request": spec.model_dump(mode="json"),
        "request_hash": spec.hash(),
        "scenario": scenario.id,
        "scenario_hash": scenario.hash(),
        "profile_hash": profile.hash(),
        "contracts_hash": contracts_hash(contracts),
        "code_commit": commit,
        "versions": versions(),
    }


def write_whatif(
    result: WhatIfResult,
    out: Path,
    profile: Profile,
    contracts: ContractLibrary,
    commit: str,
) -> Path:
    """Write the evidence of *result* under *out* and return it."""
    spec = result.spec
    scenario = load_whatif_scenario(spec.scenario)
    branches: dict[str, Any] = {}
    listed: dict[str, str] = {}
    for name, branch in result.branches.items():
        if not branch.available or branch.run is None:
            branches[name] = {
                "available": False, "reason": branch.unavailable_reason, "label": branch.label,
            }  # fmt: skip
            continue
        extra = {"series.json": _json(branch.series), "branch.json": _json(branch.summary())}
        if branch.agent_log:
            extra["agent_log.json"] = _json(branch.agent_log)
        block = {
            "request_hash": spec.hash(), "branch": name, "label": branch.label,
            "hypothetical": branch.hypothetical, "override": branch.override,
        }  # fmt: skip
        bundle = _extend(
            build_bundle(branch.run, profile, scenario, contracts, commit), extra, block
        )
        where = f"branches/{LETTERS[name]}-{name}"
        write_bundle(bundle, out / where)
        listed[f"{where}/manifest.json"] = _sha(bundle["manifest.json"])
        branches[name] = {
            "available": True, "bundle": where, "label": branch.label,
            "hypothetical": branch.hypothetical,
            "operating_profile": branch.operating_profile, "gate": branch.gate,
            "gate_commit": branch.run.gate_commit, "agent": branch.agent,
            "start_state_hash": branch.start_state_hash,
            "final_state_hash": branch.run.state_hashes[-1][1] if branch.run.state_hashes else "",
        }  # fmt: skip
    governed = result.branches.get("governed")
    manifest = {
        **_common(spec, profile, contracts, commit),
        "kind": "agentic-datacenter-whatif",
        "remora": {
            "governed_branch": governed.run.gate_commit
            if governed is not None and governed.run is not None
            else None,
            "policy_analysis": result.policy.get("remora"),
        },  # fmt: skip
        "start_state_hashes": result.start_state_hashes,
        "branches": branches,
        "statements": result.summary()["statements"],
        "files": listed,
    }
    files = {
        "summary.json": _json(result.summary()),
        "series.json": _json(result.series()),
        "preflight.json": _json(result.preflight),
        "policy.json": _json(result.policy),
    }
    return _top(out, files, manifest)


def write_policy(
    policy: Mapping[str, Any],
    spec: WhatIfSpec,
    out: Path,
    profile: Profile,
    contracts: ContractLibrary,
    commit: str,
) -> Path:
    """Write a policy analysis made alone (``agentic-datacenter whatif policy``) as a bundle."""
    manifest = {
        **_common(spec, profile, contracts, commit),
        "kind": "agentic-datacenter-whatif-policy",
        "remora": {"policy_analysis": policy.get("remora")},
        "start_state_hash": policy.get("start_state_hash"),
        "statements": [
            "An analysis of REMORA's policy for the call, made apart from any simulation of "
            "its effect. It grants nothing, proposes nothing and writes nothing.",
        ],
    }
    return _top(out, {"policy.json": _json(dict(policy))}, manifest)


def verify_whatif(directory: Path) -> list[str]:
    """Return what is wrong with the what-if evidence in *directory*; nothing if it is intact."""
    problems = verify_bundle(directory)
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return problems
    for name, entry in sorted(dict(manifest.get("branches", {})).items()):
        if isinstance(entry, dict) and entry.get("bundle"):
            problems += [f"{name}: {p}" for p in verify_bundle(directory / str(entry["bundle"]))]
    return problems
