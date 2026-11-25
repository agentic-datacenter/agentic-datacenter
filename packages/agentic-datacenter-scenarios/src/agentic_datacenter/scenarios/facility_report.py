"""``facility check``: what a facility of its owner's is, how it runs, and what fits it (ADR 0033).

The report has three parts:

- the facility: its name, its files and their hashes, its equipment models and
  its values counted by provenance;
- a run of five simulated minutes with no agent and no event, with the IT power
  served against the sum of the design loads, and the power drawn at the
  incomers;
- what fits: the contracts that load and those that do not, the scenarios that
  run and those that do not, each with the first thing it lacks.

It is a report on the description, not on the site it describes.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agentic_datacenter.core.facility import Facility
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.facility_fit import fit_facility
from agentic_datacenter.scenarios.plant import BuiltinPlant
from agentic_datacenter.scenarios.scenario import library_ids

CHECK_SECONDS = 300
#: Things the facility cannot vary yet (ADR 0033, decision 7).
FIXED = (
    "two utility incomers per MV switchgear",
    "six zone sensors per POD",
    "the oracle's limits of 27 degC and 32 degC supply air",
)


def check_facility(facility: Facility, library: ContractLibrary) -> dict[str, Any]:
    """Return the report of :mod:`facility check <agentic_datacenter.scenarios.facility_report>`."""
    kernel = Kernel(seed=0)
    plant = BuiltinPlant(facility.profile, kernel)
    kernel.run_for(CHECK_SECONDS * 1000)
    harm = plant.harm()
    design = sum(
        float(str(spec.params.get("design_kw", 150.0)))
        for spec in facility.profile.instances()
        if spec.module_id == "electrical.it_load"
    )
    fit = fit_facility(facility.profile, library, library_ids())
    return {
        "facility": facility.summary(),
        "run": {
            "seconds": CHECK_SECONDS,
            "it_design_kw": design,
            "it_served_kw": round(sum(harm.it_served_kw), 3),
            "facility_kw": round(sum(harm.facility_in_kw), 3),
            "hottest_supply_air_c": round(max(harm.supply_air_c, default=0.0), 3),
        },
        "fit": fit.block(),
        "fixed": list(FIXED),
        "statement": (
            "A report on this description of a facility, made by a generic simulator at "
            "fidelity F1. It says nothing about the real site."
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    facility, run, fit = report["facility"], report["run"], report["fit"]
    lines = [
        f"# Facility check: {facility['name']}",
        "",
        report["statement"],
        "",
        f"- Site: {facility['site']}",
        f"- Profile hash: `{facility['profile_hash']}`",
        f"- Files: {len(facility['files'])}; equipment models: {len(facility['equipment'])}",
        f"- Values: {facility['values'].get('sourced', 0)} sourced, "
        f"{facility['values'].get('assumed', 0)} assumed",
        "",
        f"## A run of {run['seconds']} s with no agent",
        "",
        f"- IT load served: {run['it_served_kw']} kW of {run['it_design_kw']} kW design",
        f"- Power at the incomers: {run['facility_kw']} kW",
        f"- Hottest supply air: {run['hottest_supply_air_c']} degC",
        "",
        "## Contracts",
        "",
        f"Loaded: {', '.join(fit['contracts_loaded']) or 'none'}",
        "",
    ]
    if fit["contracts_not_loaded"]:
        lines += ["| Not loaded | Why |", "| --- | --- |"]
        lines += [f"| `{c}` | {why} |" for c, why in fit["contracts_not_loaded"].items()]
        lines.append("")
    lines += ["## Scenarios", "", f"Run: {', '.join(fit['scenarios_run']) or 'none'}", ""]
    if fit["scenarios_not_run"]:
        lines += ["| Not run | Why |", "| --- | --- |"]
        lines += [f"| `{c}` | {why} |" for c, why in fit["scenarios_not_run"].items()]
        lines.append("")
    lines += ["## Not variable yet", ""] + [f"- {item}" for item in report["fixed"]]
    return "\n".join(lines) + "\n"


def write_report(report: dict[str, Any], out: Path) -> None:
    """Write ``facility_report.json`` and ``facility_report.md`` into *out*."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "facility_report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (out / "facility_report.md").write_text(_markdown(report), encoding="utf-8")
