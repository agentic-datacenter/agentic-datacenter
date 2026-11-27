"""Evidence bundles (SDD 12, ADC-EVD-001).

A bundle is a directory that says what was run and what happened, in a form
that can be checked without the simulator: a manifest with the hashes of the
profile, the scenario and the contracts, the seed, the code commit, the gate
and its commit, and beside it the per-minute state hashes, every decision
record, the change log of the command service, the escalations and the metric
summary. The manifest carries the hash of every other file.

The same run always gives the same bytes, so a bundle reproduced on a second
machine can be compared file by file.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.bench import STATEMENTS, lowest_fidelity
from agentic_datacenter.scenarios.harness import RunResult
from agentic_datacenter.scenarios.llm_agent import agent_kind, agent_note
from agentic_datacenter.scenarios.scenario import Scenario
from agentic_datacenter.scenarios.trace import action_trace, render_trace

BUNDLE_SCHEMA_VERSION = 1
__all__ = [
    "MEASURED_STATEMENT",
    "STATEMENTS",
    "build_bundle",
    "code_commit",
    "measured_inputs",
    "verify_bundle",
    "write_bundle",
]

#: Added to the statements of a run that used a measured input series (ADR 0018).
MEASURED_STATEMENT = (
    "Some inputs of this run are derived from a measured historical series, listed under "
    "measured_inputs. They describe the place and time the series was measured, not the "
    "simulated facility, and no value in this run is a measurement of the simulated plant."
)

#: For each module that can read a measured series, the point fed by each column.
MEASURED_POINTS = {
    "cooling.weather": {"dry_bulb": "dry_bulb_c", "rel_humidity": "rel_humidity_pct"},
}


def measured_inputs(profile: Profile, warmup_s: int, duration_s: int) -> list[dict[str, Any]]:
    """Return what the bundle records about every measured series *profile* uses.

    Simulated t=0, which the anchor stands for, is the start of the warm-up, so
    the run reads the series for *warmup_s* plus *duration_s* seconds.

    Each entry names the module instance and the points derived from the series,
    marks them as derived from a measured series and not as measurements of the
    simulated plant, and carries the anchor, the window of the series the run
    covered, any gaps bridged inside it, and the dataset's identity and licence
    as its manifest states them.
    """
    out: list[dict[str, Any]] = []
    for spec in profile.instances():
        if spec.params.get("source") != "measured":
            continue
        # The optional distribution is needed only by a run that used it, and such
        # a run could not have started without it.
        from agentic_datacenter.data import format_utc, load_series, parse_utc_ms

        series = load_series(Path(str(spec.params["manifest"])))
        anchor = str(spec.params["anchor_utc"])
        start = parse_utc_ms(anchor)
        end = start + 1000 * (warmup_s + duration_s)
        columns = MEASURED_POINTS.get(spec.module_id, {})
        gaps = [
            {"column": column, "from_utc": format_utc(t0), "to_utc": format_utc(t1)}
            for column in series.columns
            for t0, t1 in series.gaps(column, start, end)
        ]
        out.append(
            {
                "instance": f"{spec.module_id}[{spec.instance}]",
                "points": [columns[c] for c in series.columns if c in columns],
                "derived_from_measured_series": True,
                "measurement_of_simulated_plant": False,
                "anchor_utc": anchor,
                "window_utc": [format_utc(start), format_utc(end)],
                "scenario_start_utc": format_utc(start + 1000 * warmup_s),
                "bridged_gaps_in_window": gaps,
                "dataset": series.provenance(),
            }
        )
    return out


def code_commit(repo: Path) -> str:
    """Return the commit of the code in *repo*, with ``+dirty`` if files differ from it."""
    try:
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
        changed = subprocess.run(
            ["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{head}+dirty" if changed else head


def _lines(rows: Sequence[Mapping[str, Any]]) -> str:
    return "".join(json.dumps(row, sort_keys=True) + "\n" for row in rows)


def build_bundle(
    result: RunResult,
    profile: Profile,
    scenario: Scenario,
    contracts: ContractLibrary,
    commit: str,
    gate_commit: str | None = None,
    gate_evidence: Mapping[str, Any] | None = None,
    language_model: Mapping[str, Any] | None = None,
    transcript: str | None = None,
) -> dict[str, str]:
    """Return the files of the bundle of one run, by name.

    The manifest says whether the agent was scripted or a language model
    (ADC-AGT-002). For a language-model agent, *language_model* is its
    provider, model, mode and usage, and *transcript* the text of its
    transcript, kept in the bundle as ``llm_transcript.jsonl``.

    *gate_commit* is the commit of the gate under test when it comes from
    another repository (for REMORA, the installed commit), else None.
    *gate_evidence* is what a gate that keeps records of its own says ties the
    run to them: under GOVERNED, REMORA's proposal ids, the hashes of the
    compiled artifacts and the result of verifying its audit chain.
    """
    contract_hash = hashlib.sha256(
        json.dumps(
            [contracts.get(i).model_dump(mode="json") for i in contracts.ids()],  # type: ignore[union-attr]
            sort_keys=True,
        ).encode()
    ).hexdigest()
    files = {
        "state_hashes.jsonl": _lines(
            [{"time_ms": ms, "state_hash": digest} for ms, digest in result.state_hashes]
        ),
        # A served gate's correlation names one execution; it is kept apart, in
        # correlation.jsonl, so the same run gives the same bytes (ADR 0036).
        "decisions.jsonl": _lines(
            [{k: v for k, v in r.items() if k != "gate_detail"} for r in result.records]
        ),
        "change_log.jsonl": _lines(result.change_log),
        "escalations.jsonl": _lines(result.escalations),
        "metrics.json": json.dumps(
            {
                "passed": result.passed,
                "failed_criteria": result.failed_criteria,
                "metrics": result.metrics.as_dict(),
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
    }
    # Each action followed end to end, with who observed each link (ADR 0038).
    traced = action_trace(result.records, result.change_log, scenario)
    files["action_trace.jsonl"] = _lines(traced)
    files["action_trace.md"] = render_trace(traced, scenario)
    if transcript is not None:
        files["llm_transcript.jsonl"] = transcript
    gate_commit = gate_commit or result.gate_commit
    kind = "none" if result.agent == "none" else agent_kind([result.agent])
    measured = measured_inputs(profile, scenario.warmup_s, result.duration_s)
    gate_evidence = gate_evidence if gate_evidence is not None else result.gate_evidence
    if gate_evidence is not None:
        files["gate_evidence.json"] = json.dumps(gate_evidence, indent=2, sort_keys=True) + "\n"
    manifest: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "scenario": result.scenario_id,
        "scenario_hash": scenario.hash(),
        "profile_hash": profile.hash(),
        "contracts_hash": contract_hash,
        "seed": result.seed,
        "duration_s": result.duration_s,
        "shortened": result.duration_s < scenario.duration_s,
        "operating_profile": result.profile,
        "gate": result.gate,
        "gate_commit": gate_commit,
        "agent": result.agent,
        "agent_kind": kind,
        "agent_note": "No agent." if kind == "none" else agent_note(kind, language_model),
        **({"language_model": dict(language_model)} if language_model is not None else {}),
        "identity": _identity(result, kind, language_model, gate_commit),
        "code_commit": commit,
        "lowest_fidelity": lowest_fidelity(profile),
        "final_state_hash": result.state_hashes[-1][1] if result.state_hashes else "",
        "statements": [*STATEMENTS, MEASURED_STATEMENT] if measured else list(STATEMENTS),
        "files": {
            name: hashlib.sha256(text.encode()).hexdigest() for name, text in sorted(files.items())
        },
    }
    if measured:
        manifest["measured_inputs"] = measured
    correlated = [
        {"proposal_id": r["proposal_id"], **dict(r["gate_detail"])}  # type: ignore[arg-type]
        for r in result.records
        if isinstance(r.get("gate_detail"), dict)
    ]
    if correlated:
        # Not hashed in the manifest: it differs between executions of the same run.
        # gate verify-receipts makes each action_ref again from decisions.jsonl.
        manifest["execution_specific"] = [CORRELATION_FILE]
    files["manifest.json"] = json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    if correlated:
        files[CORRELATION_FILE] = _lines(correlated)
    return files


def _identity(
    result: RunResult,
    kind: str,
    language_model: Mapping[str, Any] | None,
    gate_commit: str | None,
) -> dict[str, Any]:
    """Return what ran, each part with how it is known (ADR 0038).

    ``verified_here`` is a digest made from what is installed on this machine;
    ``reported`` is a name another party gave, which nothing here can check.
    """
    from agentic_datacenter.scenarios import agents as scripted

    agent: dict[str, Any] = {"name": result.agent, "kind": kind}
    if kind == "scripted":
        agent["definition_sha256"] = hashlib.sha256(
            Path(str(scripted.__file__)).read_bytes()
        ).hexdigest()
        agent["known_by"] = "verified_here"
    elif kind == "language_model" and language_model is not None:
        usage = language_model.get("usage") or {}
        agent["model_asked"] = language_model.get("model")
        agent["models_served"] = list(usage.get("served_models") or [])
        agent["known_by"] = "reported"
    from agentic_datacenter.scenarios.bench import BUILT_IN_GATES

    gate: dict[str, Any] = {"name": result.gate}
    if gate_commit:
        gate.update(commit=gate_commit, known_by="verified_here")
    elif result.gate in BUILT_IN_GATES:
        gate["known_by"] = "built_in"  # part of code_commit
    else:
        gate["known_by"] = "reported"  # its name, as the gate gave it
    return {"agent": agent, "gate": gate}


#: The file of a bundle that holds a served gate's correlation, outside the manifest's hashes.
CORRELATION_FILE = "correlation.jsonl"
#: The record of one execution: the hash of what the manifest leaves out, and of the manifest.
EXECUTION_FILE = "execution.json"
EXECUTION_SCHEMA = "adc-execution/v1"


def records_with_correlation(directory: Path) -> list[dict[str, Any]]:
    """Return the decision records of a bundle, each with the correlation kept apart for it."""
    records = [
        json.loads(t) for t in (directory / "decisions.jsonl").read_text("utf-8").splitlines()
        if t.strip()
    ]  # fmt: skip
    path = directory / CORRELATION_FILE
    if path.is_file():
        by_id = {}
        for text in path.read_text(encoding="utf-8").splitlines():
            if text.strip():
                line = json.loads(text)
                by_id[str(line.pop("proposal_id"))] = line
        for record in records:
            if str(record.get("proposal_id")) in by_id:
                record["gate_detail"] = by_id[str(record["proposal_id"])]
    return records


def write_bundle(bundle: Mapping[str, str], out_dir: Path) -> Path:
    """Write the files of *bundle* to *out_dir* and return it."""
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, text in bundle.items():
        (out_dir / name).write_text(text, encoding="utf-8")
    if CORRELATION_FILE in bundle and "manifest.json" in bundle:
        # What differs between two executions of a run is outside the manifest, so
        # that the manifest is the same bytes each time. This record ties it to the
        # manifest of this execution, so a changed line is found (ADR 0036, ADR 0041).
        record = {
            "schema": EXECUTION_SCHEMA,
            "manifest_sha256": _sha256(bundle["manifest.json"]),
            "files": {CORRELATION_FILE: _sha256(bundle[CORRELATION_FILE])},
        }
        text = json.dumps(record, indent=2, sort_keys=True) + "\n"
        (out_dir / EXECUTION_FILE).write_text(text, encoding="utf-8")
    return out_dir


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def verify_bundle(directory: Path) -> list[str]:
    """Return what is wrong with the bundle in *directory*; nothing if it is intact."""
    try:
        manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
        listed = dict(manifest["files"])
    except (OSError, ValueError, KeyError, TypeError):
        return ["manifest.json is missing or unreadable"]
    problems = []
    for name, expected in sorted(listed.items()):
        path = directory / name
        if not path.is_file():
            problems.append(f"{name} is missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            problems.append(f"{name} does not match the hash in the manifest")
    return problems + _execution_problems(directory)


def _execution_problems(directory: Path) -> list[str]:
    """Return what is wrong with the files of one execution, which the manifest leaves out."""
    if not (directory / CORRELATION_FILE).is_file():
        return []
    try:
        record = json.loads((directory / EXECUTION_FILE).read_text(encoding="utf-8"))
        files = dict(record["files"])
        manifest = str(record["manifest_sha256"])
    except (OSError, ValueError, KeyError, TypeError):
        return [f"{CORRELATION_FILE} is there and {EXECUTION_FILE}, which holds its hash, is not"]
    problems = []
    if hashlib.sha256((directory / "manifest.json").read_bytes()).hexdigest() != manifest:
        problems.append(f"{EXECUTION_FILE} is of another manifest")
    for name, expected in sorted(files.items()):
        path = directory / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected:
            problems.append(f"{name} does not match the hash in {EXECUTION_FILE}")
    return problems
