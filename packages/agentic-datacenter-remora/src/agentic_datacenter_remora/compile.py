"""Compile the contract library to the artifacts REMORA's governed path loads (SDD 9.2).

Three files come out: a signed ToolSpec bundle (one tool per contract, its
argument schema carrying the contract's bounds, and a restore tool for each
contract with a safe direction), a signed cumulative-limit
policy (rate, cumulative movement per tag, second approver) and the risk
declaration REMORA reads for each tool. Signing is done by REMORA's own
packaged commands, ``remora build-toolspec`` and ``remora sign-limits``, run
as subprocesses; nothing here canonicalizes or signs.

The signing seeds are derived from the contract library and exist only for
the simulator. They are handed to the subprocess in its environment and never
written to disk. The artifacts are build outputs, labelled as not for
production.

What a REMORA artifact cannot say stays with the binding and is listed in the
manifest: a step limit relative to the present value, premises, rollback, and
every write of a contract after its first. A contract that would be left
without a bound anywhere fails the build.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentic_datacenter.governance.contracts import Contract, ContractLibrary

TENANT = "agentic-datacenter"
#: Never a production name: the governed path in a simulator is not one.
TARGET = "simulation"
DOMAIN = "operational-technology"
#: Ledger units per engineering unit. Limits are whole numbers of these.
SCALE = 1000
#: REMORA risk tier per contract. An R1 step with a declared rollback is
#: ``low``: REMORA's bounded-write path may then run it without a person, inside
#: the signed bounds and limits (REMORA #1234, ADR 0016). Everything else that
#: can execute is ``high`` and goes to a person.
LOW, HIGH = "low", "high"


def risk_tier(contract: Contract) -> str:
    """Return the REMORA risk tier a contract is declared at."""
    if contract.risk_tier in ("R0", "R1") and contract.rollback is not None:
        return LOW
    return HIGH


ACTION_TYPE = "write"
CALLABLE = "agentic_datacenter_remora.host_registry:apply_contract"
LABEL = "simulator artifact, not for production"
SIGNED_AT = "2000-01-01T00:00:00+00:00"
#: Stands in for "no ceiling" on a counter that exists only to ask for a second
#: approver, or only to meter a restore tool.
_NO_CEILING = 1_000_000
_VERSION = re.compile(r"\.v(\d+)$")


class CompileError(ValueError):
    """A contract cannot be expressed in REMORA's artifacts without weakening it."""


@dataclass(frozen=True)
class Compiled:
    """Where the artifacts are, and what identifies them."""

    directory: Path
    manifest: dict[str, Any]


def compiled_ids(library: ContractLibrary) -> list[str]:
    """Return the contracts that become tools: every one that can ever be executed."""
    out = []
    for contract_id in library.ids():
        contract = library.get(contract_id)
        assert contract is not None
        if contract.writes and contract.approval != "not_available":
            out.append(contract_id)
    return out


def restore_tool_id(contract_id: str) -> str:
    """Return the tool a step back toward safety is assessed under (INV-GOV-8)."""
    version = _VERSION.search(contract_id)
    if version is None:
        return f"{contract_id}.restore"
    return f"{contract_id[: version.start()]}.restore{version.group(0)}"


def restore_ids(library: ContractLibrary) -> dict[str, str]:
    """Return restore tool id -> contract id, for every contract that has a safe direction.

    The restore tool has the contract's argument schema and bounds, and its
    calls are counted, but no rate or cumulative limit is charged to it. The
    binding asks for it only for a step that goes back toward the value a
    point had before the agent's standing writes, and no further.
    """
    out = {}
    for contract_id in compiled_ids(library):
        contract = library.get(contract_id)
        assert contract is not None
        if contract.safe_direction() is not None:
            out[restore_tool_id(contract_id)] = contract_id
    return out


def tool_ids(library: ContractLibrary) -> list[str]:
    """Return every tool REMORA registers: the contracts, then their restore tools."""
    return [*compiled_ids(library), *restore_ids(library)]


def library_hash(library: ContractLibrary) -> str:
    """Return the hash that identifies a contract library."""
    dumped = []
    for contract_id in library.ids():
        contract = library.get(contract_id)
        assert contract is not None
        dumped.append(contract.model_dump(mode="json"))
    return hashlib.sha256(json.dumps(dumped, sort_keys=True).encode("utf-8")).hexdigest()


def derived_secret(library: ContractLibrary, purpose: str) -> str:
    """Return 32 bytes of hex for *purpose*, the same for the same library."""
    text = f"agentic-datacenter simulator-only secret|{purpose}|{library_hash(library)}"
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def signing_seeds(library: ContractLibrary) -> dict[str, str]:
    """Return the simulator-only signing seeds. They never reach the disk."""
    return {
        "toolspec": derived_secret(library, "toolspec signing seed"),
        "limits": derived_secret(library, "limits signing seed"),
    }


def _whole(value: float, what: str) -> int:
    scaled = round(value, 9)
    if scaled != int(scaled) or int(scaled) < 1:
        raise CompileError(f"{what} = {value:g} is not a whole number of units, 1 or more")
    return int(scaled)


def _properties(contract: Contract) -> dict[str, Any]:
    properties: dict[str, Any] = {}
    for name, argument in contract.arguments.items():
        if argument.type == "number":
            written = [w for w in contract.writes if w.value == name]
            if any(w.bounds is None for w in written):
                raise CompileError(f"{contract.id}: {name} is written with no bounds")
            schema: dict[str, Any] = {"type": "number"}
            if written:
                low = max(w.bounds.min for w in written if w.bounds)
                high = min(w.bounds.max for w in written if w.bounds)
                if low > high:
                    raise CompileError(f"{contract.id}: the bounds on {name} do not overlap")
                schema.update(minimum=low, maximum=high)
            properties[name] = schema
        elif argument.type == "choice":
            properties[name] = {"type": "string", "enum": list(argument.choices or ())}
        elif argument.type == "key":
            # The key set belongs to the facility profile; the binding refuses
            # an unknown key before REMORA is asked.
            properties[name] = {"type": "string"}
        elif argument.authoritative:
            raise CompileError(f"{contract.id}: text argument {name} cannot be bounded")
        else:
            properties[name] = {"type": "string"}
    properties["target"] = {"type": "string"}
    return properties


def _spec(contract: Contract, tool_id: str | None = None) -> dict[str, Any]:
    properties = _properties(contract)
    first = contract.writes[0]
    expected: Any = {"$arg": first.value} if first.value is not None else first.const
    version = _VERSION.search(contract.id)
    tool_id = tool_id or contract.id
    title = contract.title
    if tool_id != contract.id:
        title = f"{title}: a step back toward the value before the agent's writes"
    return {
        "tool_id": tool_id,
        "version": int(version.group(1)) if version else 1,
        "callable": CALLABLE,
        "implementation_identity": f"{CALLABLE.replace(':', '.')}@agentic-datacenter",
        "description": title,
        "argument_schema": {
            "type": "object",
            "properties": properties,
            "required": sorted(properties),
            "additionalProperties": False,
        },
        "risk_tier": risk_tier(contract),
        "action_type": ACTION_TYPE,
        "domain": DOMAIN,
        "capabilities": [tool_id],
        "semantic_contract": {
            "capability": tool_id,
            "effect": "update",
            "resource_type": "plant_point",
            "mutation": True,
            "argument_roles": {"target": "target_resource"},
        },
        "credential_scope": [f"agentic-datacenter:{tool_id}"],
        "allowed_targets": [TARGET],
        "idempotency_contract": {"safe_to_retry": False, "key_derivation": "canonical_args"},
        "postcondition_reader": "agentic-datacenter-plant-reader",
        "postcondition": {
            "target_selector": {"tag": {"$arg": "target"}},
            "expected_fields": {"value": expected},
            "comparison_rules": {"value": "exact"},
        },
        "compensation_tool": None,
        "timeout_policy": {"dispatch_timeout_seconds": 15},
        "network_policy": {"egress": "none"},
    }


def unsigned_bundle(library: ContractLibrary) -> dict[str, Any]:
    """Return the ToolSpec bundle before REMORA measures and signs it."""
    specs = []
    for contract_id in compiled_ids(library):
        contract = library.get(contract_id)
        assert contract is not None
        specs.append(_spec(contract))
    for tool_id, contract_id in restore_ids(library).items():
        contract = library.get(contract_id)
        assert contract is not None
        specs.append(_spec(contract, tool_id))
    if not specs:
        raise CompileError("the library has no contract that can be executed")
    return {"schema_version": 5, "tool_specs": specs}


def limits_policy(library: ContractLibrary) -> dict[str, Any]:
    """Return the cumulative-limit policy before REMORA validates and signs it.

    A contract's rate is a count of calls per written point. Its cumulative
    limit is the movement of the first point it writes, and contracts that
    write the same point share that counter (INV-GOV-6): the strictest of
    their limits applies. A contract that needs two people asks for the second
    from the first call.
    """
    meters: dict[str, list[dict[str, Any]]] = {}
    limits: dict[str, dict[str, Any]] = {}
    for contract_id in compiled_ids(library):
        contract = library.get(contract_id)
        assert contract is not None
        calls = f"calls:{contract.id}"
        meters[contract.id] = [
            {"quantity": calls, "kind": "count", "unit": "calls", "resource_argument": "target"}
        ]
        rate, two = contract.limits.rate, contract.approval == "two_person"
        if rate is not None or two:
            limit: dict[str, Any] = {
                "limit_id": f"rate:{contract.id}",
                "tenant": TENANT,
                "quantity": calls,
                "unit": "calls",
                "resource": "*",
                "principal": "*",
                "max": rate.max_per_hour if rate is not None else _NO_CEILING,
                "window_seconds": 3600,
            }
            if two:
                limit["dual_control_above"] = 0
            limits[limit["limit_id"]] = limit
        cumulative, first = contract.limits.cumulative, contract.writes[0]
        if cumulative is None:
            continue
        if first.value is None or first.bounds is None:
            raise CompileError(f"{contract.id}: a cumulative limit needs a bounded numeric write")
        unit = first.bounds.unit or "units"
        quantity = f"movement:{first.tag}"
        meters[contract.id].append({
            "quantity": quantity, "kind": "change", "argument": first.value, "scale": SCALE,
            "unit": unit, "resource_argument": "target", "observed": True,
        })  # fmt: skip
        ceiling = _whole(cumulative.max_total_delta * SCALE, f"{contract.id}: cumulative limit")
        window = _whole(cumulative.window_h * 3600, f"{contract.id}: cumulative window in seconds")
        limit_id = f"cumulative:{first.tag}"
        earlier = limits.get(limit_id)
        if earlier is not None:
            ceiling = min(ceiling, int(earlier["max"]))
            window = max(window, int(earlier["window_seconds"]))
        limits[limit_id] = {
            "limit_id": limit_id, "tenant": TENANT, "quantity": quantity, "unit": unit,
            "resource": "*", "principal": "*", "max": ceiling, "window_seconds": window,
        }  # fmt: skip
    for tool_id in restore_ids(library):
        # Counted, so every write is metered and declared, and never held (INV-GOV-8).
        calls = f"calls:{tool_id}"
        meters[tool_id] = [
            {"quantity": calls, "kind": "count", "unit": "calls", "resource_argument": "target"}
        ]
        limits[f"rate:{tool_id}"] = {
            "limit_id": f"rate:{tool_id}", "tenant": TENANT, "quantity": calls, "unit": "calls",
            "resource": "*", "principal": "*", "max": _NO_CEILING, "window_seconds": 3600,
        }  # fmt: skip
    return {
        "schema": "remora-cumulative-limits/v1",
        "coverage": "all_writes",
        "meters": meters,
        "limits": [limits[key] for key in sorted(limits)],
    }


def tool_metadata(library: ContractLibrary) -> dict[str, Any]:
    """Return the risk declaration REMORA reads for each tool."""
    tools = {}
    for contract_id in compiled_ids(library):
        contract = library.get(contract_id)
        assert contract is not None
        tools[contract_id] = {
            "risk_tier": risk_tier(contract), "domain": DOMAIN, "action_type": ACTION_TYPE,
            "schema_valid": True, "rollback_available": contract.rollback is not None,
        }  # fmt: skip
    for tool_id, contract_id in restore_ids(library).items():
        tools[tool_id] = dict(tools[contract_id])
    return {"version": 1, "tools": tools}


def _kept(contract: Contract) -> list[str]:
    kept = []
    if any(w.bounds is not None and w.bounds.max_step is not None for w in contract.writes):
        kept.append("max_step")
    if contract.premises:
        kept.append("premises")
    if contract.rollback is not None:
        kept.append("rollback")
    if len(contract.writes) > 1:
        kept.append("writes beyond the first")
    return kept


def _remora(arguments: list[str], seed_name: str, seed: str) -> subprocess.CompletedProcess[str]:
    """Run one ``remora`` command of the installed package with a seed in its environment."""
    environment = {k: v for k, v in os.environ.items() if not k.startswith("REMORA_")}
    environment[seed_name] = seed
    done = subprocess.run(  # noqa: S603 - fixed arguments, the installed interpreter
        [sys.executable, "-m", "remora", *arguments],
        capture_output=True, text=True, env=environment, check=False,
    )  # fmt: skip
    if done.returncode != 0:
        raise CompileError(f"remora {arguments[0]} refused: {done.stderr.strip()[-400:]}")
    return done


def compile_contracts(
    library: ContractLibrary, out_dir: Path, signed_at: str = SIGNED_AT
) -> Compiled:
    """Write the signed ToolSpec bundle, the signed limits and the tool metadata.

    Raises:
        CompileError: If a contract cannot be expressed, or REMORA refuses an
            artifact. Nothing is left in *out_dir* then.
    """
    bundle, policy, metadata = (
        unsigned_bundle(library),
        limits_policy(library),
        tool_metadata(library),
    )
    seeds = signing_seeds(library)
    with tempfile.TemporaryDirectory() as scratch:
        work = Path(scratch)
        (work / "bundle.json").write_text(json.dumps(bundle, sort_keys=True), encoding="utf-8")
        (work / "policy.json").write_text(json.dumps(policy, sort_keys=True), encoding="utf-8")
        signed = _remora(
            ["build-toolspec", str(work / "bundle.json"), "--out", str(work / "signed.json"),
             "--signed-at", signed_at],
            "REMORA_TOOLSPEC_SIGNING_SEED", seeds["toolspec"],
        )  # fmt: skip
        identity = json.loads(signed.stdout)
        limits = _remora(
            ["sign-limits", str(work / "policy.json"), "--out", str(work / "limits.json"),
             "--signed-at", signed_at.replace("+00:00", "Z")],
            "REMORA_LIMITS_SIGNING_SEED", seeds["limits"],
        )  # fmt: skip
        public = re.search(r"public key to trust:\s*([0-9a-f]{64})", limits.stderr)
        if public is None:
            raise CompileError("remora sign-limits did not name its public key")
        files = {
            "toolspec-bundle.json": (work / "signed.json").read_text(encoding="utf-8"),
            "limits.json": (work / "limits.json").read_text(encoding="utf-8"),
            "tool_metadata.json": json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        }
    kept = {}
    for contract_id in compiled_ids(library):
        contract = library.get(contract_id)
        assert contract is not None
        kept[contract_id] = _kept(contract)
    for tool_id, contract_id in restore_ids(library).items():
        kept[tool_id] = [*kept[contract_id], "a step back only to where the agent started"]
    manifest: dict[str, Any] = {
        "label": LABEL,
        "library_sha256": library_hash(library),
        "sha256": {
            name: hashlib.sha256(text.encode("utf-8")).hexdigest() for name, text in files.items()
        },
        "toolspec_verify_key": identity["public_key"],
        "toolspec_pinned_digest": identity["pinned_digest"],
        "toolspec_signing_identity": identity["signing_identity"],
        "limits_public_key": public.group(1),
        "scale": SCALE,
        "tools": tool_ids(library),
        "restore_tools": restore_ids(library),
        "enforced_by_the_binding": kept,
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in files.items():
        (out_dir / name).write_text(text, encoding="utf-8")
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return Compiled(out_dir, manifest)
