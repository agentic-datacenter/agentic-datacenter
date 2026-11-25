"""Evidence tables and outdoor-temperature charts shared by the demo reports."""

from __future__ import annotations

import hashlib
import html
import json
import math
from collections.abc import Mapping, Sequence
from typing import Any

Table = tuple[str, tuple[str, ...], Sequence[tuple[str, ...]]]
MISSING = "Not recorded"
COLORS = ("#007a8a", "#ca6622", "#9470c7", "#408049", "#b84974")


def recording_text(demo: Mapping[str, Any]) -> str:
    """Exact serialization used for the recording and its reported digest."""
    return json.dumps(demo, indent=2, sort_keys=True) + "\n"


def _text(value: Any) -> str:
    if value is None or value == "":
        return MISSING
    if isinstance(value, (Mapping, list, tuple)):
        return json.dumps(value, sort_keys=True, ensure_ascii=False)
    return str(value)


def _number(value: Any) -> str:
    usable = isinstance(value, (int, float)) and not isinstance(value, bool)
    if not usable or not math.isfinite(value):
        return MISSING
    return f"{value:,.3f}".rstrip("0").rstrip(".")


def _seconds(value: Any) -> str:
    """Return *value* in seconds with its unit, or the missing text with none."""
    text = _text(value)
    return text if text == MISSING else f"{text} s"


def _range(values: Sequence[Any]) -> str:
    numbers = [
        v
        for v in values
        if isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
    ]
    return f"{min(numbers):g} to {max(numbers):g}" if numbers else MISSING


def _impact(decision: Mapping[str, Any]) -> int:
    replay = decision.get("counterfactual") or {}
    if replay.get("kind") in ("harm_avoided", "false_block"):
        return 0
    if decision.get("outcome") in ("ROLLED_BACK", "UNKNOWN"):
        return 1
    if decision.get("outcome") == "APPLIED":
        return 2
    return 3


def _actions(sides: Sequence[Mapping[str, Any]]) -> Sequence[tuple[str, ...]]:
    rows = []
    for side in sides:
        decisions = side.get("decisions", ())
        selected = sorted(sorted(decisions, key=_impact)[:3], key=lambda d: d["time_s"])
        for d in selected:
            record = d.get("record") or {}
            reasons = record.get("reasons") or record.get("reason_codes") or []
            outcome = " / ".join(filter(None, (d.get("verdict"), d.get("outcome"))))
            if d.get("outcome_detail"):
                outcome += f" ({d['outcome_detail']})"
            replay = d.get("counterfactual")
            delta = "No replay recorded for this proposal"
            if replay:
                delta = (
                    f"{_text(replay.get('kind'))}; "
                    f"delta critical POD-min {_number(replay.get('delta_critical_pod_minutes'))}, "
                    f"delta unserved IT kWh {_number(replay.get('delta_it_kwh_lost'))}, "
                    f"delta facility kWh {_number(replay.get('delta_facility_kwh'))}"
                )
                if replay.get("label") == "not_executable":
                    delta = "Proposal could not be executed in replay"
            rows.append(
                (
                    str(side["gate"]),
                    str(d["time_s"]),
                    str(d["proposal_id"]),
                    f"{d['contract_id']} {_text(d.get('arguments'))}",
                    outcome,
                    "; ".join(map(str, reasons)) or MISSING,
                    delta,
                )
            )
    return rows


def _conditions(sides: Sequence[Mapping[str, Any]]) -> Sequence[tuple[str, ...]]:
    rows = []
    for side in sides:
        gate = str(side["gate"])
        for tag, point in sorted(side.get("telemetry", {}).items()):
            signal = (
                "Outdoor dry-bulb temperature"
                if tag.endswith(".dry_bulb_c")
                else "Outdoor relative humidity"
            )
            rows.append((gate, f"{signal} · {tag}", point["unit"], _range(point["values"])))
        for key, label in (
            ("facility_in_kw", "Facility incoming power"),
            ("it_served_kw", "IT power served"),
        ):
            samples = side.get("series", {}).get(key)
            if samples:
                rows.append((gate, label, "kW", _range(samples)))
    return rows


def _run_metrics(sides: Sequence[Mapping[str, Any]]) -> Sequence[tuple[str, ...]]:
    rows = []
    for side in sides:
        m = side["metrics"]
        temperatures = side.get("series", {}).get("hottest_pod_c") or ()
        rows.append(
            (
                str(side["gate"]),
                str(side["profile"]),
                "Pass" if side["passed"] else "Fail",
                _number(max(temperatures, default=None)),
                _number(m.get("excursion_pod_minutes")),
                _number(m.get("critical_pod_minutes")),
                _number(m.get("it_kwh_lost")),
                _number(m.get("it_kwh")),
                _number(m.get("facility_kwh")),
                _number(m.get("pue")),
                _text(m.get("alarms_raised")),
                _text(m.get("protection_trips")),
                _text(m.get("proposals")),
                _text(m.get("blocked")),
                _text(m.get("approvals_requested")),
                _text(m.get("executed_over_limit")),
                _text(m.get("executed_without_required_approval")),
                _text(m.get("executed_without_authority")),
                _text(m.get("unknown_unresolved")),
            )
        )
    return rows


def comparison_overview(demo: Mapping[str, Any]) -> Table:
    """Provide an equally scoped opening comparison for all selected controls."""
    rows = []
    for scenario in demo["scenarios"]:
        for side in scenario["sides"]:
            metrics = side["metrics"]
            temperatures = side.get("series", {}).get("hottest_pod_c") or ()
            rows.append(
                (
                    str(scenario["scenario"]),
                    str(side["gate"]),
                    str(side["profile"]),
                    "Pass" if side["passed"] else "Fail",
                    _number(max(temperatures, default=None)),
                    _number(metrics.get("it_kwh_lost")),
                    _number(metrics.get("facility_kwh")),
                    _text(metrics.get("executed_over_limit")),
                )
            )
    return (
        "Comparison at a glance",
        (
            "Scenario",
            "Control",
            "Operating profile",
            "Criteria",
            "Peak IT supply °C",
            "IT lost kWh",
            "Facility kWh",
            "Writes over limit",
        ),
        rows,
    )


def report_sections(demo: Mapping[str, Any]) -> list[tuple[str, list[str], list[Table]]]:
    """Use recorded fields only. Older recordings retain explicit coverage gaps."""
    facility = demo.get("facility") or {}
    digest = hashlib.sha256(recording_text(demo).encode()).hexdigest()
    intro = [
        f"Recording SHA-256 (demo.json): {digest}",
        f"Seed: {_text(demo.get('seed'))}. Lowest module fidelity: "
        f"{_text(demo.get('lowest_fidelity'))}.",
        "Controls within a scenario use the same configured model and seed. "
        "Agent proposals can diverge as plant state changes. Facility energy and PUE must be "
        "read together with IT energy served and lost.",
        "Replay deltas compare forcing a blocked proposal through with leaving it blocked over the "
        "replay window. They are simulated estimates and cannot be added across proposals.",
    ]
    if not facility:
        intro.append("The resolved facility configuration was not recorded in this capture.")
    if not any(s.get("manifest") for sc in demo["scenarios"] for s in sc["sides"]):
        intro.append(
            "This recording has no attached manifests. Its sha256 identifies the "
            "recording, and does not establish the code or input versions."
        )
    setup: list[Table] = []
    if facility:
        setup.append(
            (
                "Facility configuration",
                ("Field", "Recorded value"),
                [
                    ("Profile", _text(facility.get("name"))),
                    ("Resolved profile hash", _text(facility.get("profile_hash"))),
                    ("Parameter provenance counts", _text(facility.get("values"))),
                    (
                        "Scenarios excluded by facility fit",
                        _text(facility.get("scenarios_not_run", {})),
                    ),
                ],
            )
        )
    inventory = [
        (tag, str(info["module"]), "Stub" if info.get("stub") else "Model")
        for tag, info in sorted(facility.get("instances", {}).items())
    ]
    if inventory:
        setup.append(
            ("Modeled equipment and systems", ("Instance", "Module", "Implementation"), inventory)
        )
    equipment = [
        (
            key,
            _text(info.get("module")),
            _text(info.get("maker")),
            _text(info.get("model")),
            _text(info.get("evidence")),
        )
        for key, info in sorted(facility.get("equipment", {}).items())
    ]
    if equipment:
        setup.append(
            (
                "Equipment models declared in the bundle",
                ("ID", "Module", "Maker", "Model", "Source"),
                equipment,
            )
        )
    files = [(path, digest) for path, digest in sorted(facility.get("files", {}).items())]
    if files:
        setup.append(("Facility bundle inputs", ("File", "SHA-256"), files))

    sections = [("Run inputs and evidence", intro, setup)]
    for sc in demo["scenarios"]:
        sides = sc["sides"]
        notes = [
            f"Scripted agent: {_text(sc.get('agent'))}. "
            f"Recorded span: {_seconds(sc.get('duration_s'))} of "
            f"{_seconds(sc.get('full_duration_s'))}. "
            f"Warm-up: {_seconds(sc.get('warmup_s'))}.",
            "Headline plant harm means critical supply-air exposure or unserved IT energy. "
            "See operating outcomes for protection trips, approvals and additional checks.",
            "The outcomes table shows run totals. Proposal examples include up to three "
            "per control, prioritizing replay impact, rollback or uncertainty, and applied "
            "writes. The technical dashboard and recording contain every proposal.",
        ]
        if "sample_every_s" in sc:
            notes.append(
                f"Telemetry sample interval: {sc['sample_every_s']} s; "
                "the final sample is included. Reported ranges are sampled ranges."
            )
        conditions = _conditions(sides)
        if not any(side.get("telemetry") for side in sides):
            notes.append("Outdoor conditions were not recorded.")
        events = [
            (str(e["at_s"]), _text({k: v for k, v in e.items() if k != "at_s"}))
            for e in sc.get("events", ())
        ]
        if "events" not in sc:
            notes.append("Scenario event timeline was not recorded.")
        elif not events:
            notes.append("No scenario event was scheduled inside the recorded window.")
        failures = [
            (str(side["gate"]), str(failure))
            for side in sides
            for failure in side.get("failed_criteria", ())
        ]
        if not failures:
            notes.append("No failed scenario criteria are listed for these runs.")
        metric_rows = _run_metrics(sides)
        metric_names = (
            "Gate",
            "Profile",
            "Scenario criteria",
            "Hottest sampled IT supply air (°C)",
            "Excursion POD-min",
            "Critical POD-min",
            "IT lost kWh",
            "IT served kWh",
            "Facility kWh",
            "PUE",
            "Alarms",
            "Protection trips",
            "Agent proposals",
            "Blocked proposals",
            "Approval requests",
            "Writes over limit",
            "Writes missing approval",
            "Writes outside mandate",
            "Unresolved outcomes",
        )
        comparison = list(zip(metric_names, *metric_rows, strict=True))
        tables: list[Table] = [
            ("Operating outcomes", comparison[0], comparison[1:]),
            (
                "Scenario events (scheduled injection time)",
                ("Scenario time (s)", "Event and parameters"),
                events,
            ),
            (
                "Outdoor conditions and electrical load",
                ("Gate", "Sampled signal", "Unit", "Observed range"),
                conditions,
            ),
            ("Failed scenario criteria", ("Gate", "Criterion"), failures),
            (
                "Agent proposals and outcomes",
                (
                    "Gate",
                    "Time (s)",
                    "Proposal ID",
                    "Requested action",
                    "Decision and outcome",
                    "Recorded reasons",
                    "Counterfactual effect",
                ),
                _actions(sides),
            ),
        ]
        manifests = []
        measured: list[tuple[str, ...]] = []
        for side in sides:
            manifest = side.get("manifest")
            if manifest is None:
                continue
            evidence = side.get("evidence")
            manifests.append(
                (
                    str(side["gate"]),
                    _text(manifest.get("code_commit")),
                    _text(manifest.get("gate_commit")),
                    _text(manifest.get("scenario_hash")),
                    _text(manifest.get("contracts_hash")),
                    _text(side.get("final_state_hash")),
                    f"agentic-datacenter scenario verify {evidence}" if evidence else MISSING,
                )
            )
            if not measured and manifest.get("measured_inputs"):
                measured = [
                    (
                        _text(item.get("instance")),
                        _text(item.get("window_utc")),
                        _text(item.get("dataset")),
                        _text(item.get("bridged_gaps_in_window")),
                    )
                    for item in manifest["measured_inputs"]
                ]
        if not measured and conditions:
            notes.append(
                "Weather samples are model inputs. A measured source is identified "
                "only when it is present in a run manifest."
            )
        tables.extend(
            (
                (
                    "Measured input provenance",
                    ("Instance", "UTC window", "Dataset", "Bridged gaps"),
                    measured,
                ),
                (
                    "Evidence manifests",
                    (
                        "Gate",
                        "Simulator commit",
                        "Gate commit",
                        "Scenario hash",
                        "Contracts hash",
                        "Final state hash",
                        "Verify from the report directory",
                    ),
                    manifests,
                ),
            )
        )
        sections.append((f"{sc['scenario']} · evidence review", notes, tables))
    return sections


def _md(value: str) -> str:
    return (
        html.escape(value, quote=False).replace("|", "\\|").replace("\n", " ").replace("`", "\\`")
    )


def _table_markdown(table: Table) -> list[str]:
    name, headers, rows = table
    return [
        f"#### {_md(name)}",
        "",
        "| " + " | ".join(map(_md, headers)) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(map(_md, row)) + " |" for row in rows),
        "",
    ]


def overview_markdown(demo: Mapping[str, Any]) -> str:
    """Render the multi-control overview."""
    return "\n".join(_table_markdown(comparison_overview(demo)))


def evidence_markdown(demo: Mapping[str, Any]) -> str:
    """Render the evidence tables as GitHub-compatible Markdown."""
    lines: list[str] = []
    for title, notes, tables in report_sections(demo):
        lines.extend((f"## {_md(title)}", ""))
        for note in notes:
            lines.extend((_md(note), ""))
        for table in tables:
            if table[2]:
                lines.extend(_table_markdown(table))
    return "\n".join(lines)


def _telemetry_figures(scenario: Mapping[str, Any]) -> str:
    """Plot recorded telemetry on shared per-signal scales across controls."""
    series: dict[tuple[str, str], list[tuple[str, list[tuple[float, float | None]]]]] = {}

    for side in scenario["sides"]:
        times = side.get("series", {}).get("t_s", ())
        gate = str(side["gate"])
        signals = [
            (f"Outdoor dry-bulb temperature · {tag}", "°C", point["values"])
            for tag, point in side.get("telemetry", {}).items()
            if tag.endswith(".dry_bulb_c")
        ]
        for key, title, unit in (
            ("hottest_pod_c", "Hottest IT supply air", "°C"),
            ("it_served_kw", "IT power served", "kW"),
            ("facility_in_kw", "Facility incoming power", "kW"),
        ):
            if key == "hottest_pod_c" and len(scenario["sides"]) < 3:
                continue
            if samples := side.get("series", {}).get(key):
                signals.append((title, unit, samples))
        for title, unit, samples in signals:
            if len(times) == len(samples):
                series.setdefault((title, unit), []).append(
                    (
                        gate,
                        list(zip(times, samples, strict=True)),
                    )
                )
    figures = []
    for (title, unit), runs in sorted(series.items()):
        values = [v for _, samples in runs for _, v in samples if v is not None]
        if not values:
            continue
        low, high = min(values), max(values)
        if low == high:
            low, high = low - 1, high + 1
        duration = max(1, scenario["duration_s"])
        marks = []
        legend = []
        for index, (gate, samples) in enumerate(runs):
            color = COLORS[index % len(COLORS)]
            path = []
            start = True
            for time, value in samples:
                if value is None:
                    start = True
                    continue
                x, y = 57 + 430 * time / duration, 150 - 130 * (value - low) / (high - low)
                path.append(f"{'M' if start else 'L'}{x:.2f},{y:.2f}")
                if start:
                    marks.append(f'<circle cx="{x:.2f}" cy="{y:.2f}" r="2" fill="{color}"/>')
                start = False
            if path:  # no line at all when every sample is missing
                marks.append(
                    f'<path d="{" ".join(path)}" fill="none" stroke="{color}" stroke-width="2" '
                    f'stroke-dasharray="{index * 2} {index}" />'
                )
            legend.append(f'<li style="border-left:4px solid {color}">{html.escape(gate)}</li>')
        figures.append(
            " <figure><figcaption>"
            f'{html.escape(title)}</figcaption><svg viewBox="0 0 520 180" role="img" '
            f'aria-label="{html.escape(title)} ({unit}) over simulated time">'
            '<path d="M57 20V150H487" fill="none" stroke="currentColor"/>'
            f'<text x="0" y="25" fill="currentColor">{high:g} {unit}</text>'
            f'<text x="0" y="153" fill="currentColor">{low:g} {unit}</text>'
            '<text x="57" y="172" fill="currentColor">0 s</text>'
            f'<text x="487" y="172" text-anchor="end" fill="currentColor">{duration} s</text>'
            + "".join(marks)
            + "</svg><ul>"
            + "".join(legend)
            + "</ul></figure>"
        )
    return "".join(figures)


def _table_html(table: Table) -> str:
    name, headers, rows = table
    esc = html.escape
    head = "".join(f"<th scope='col'>{esc(h)}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{esc(value)}</td>" for value in row) + "</tr>" for row in rows
    )
    return (
        f"<h3>{esc(name)}</h3><div class='evidence-table'><table>"
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
    )


def overview_html(demo: Mapping[str, Any]) -> str:
    """Render an HTML overview featuring all controls."""
    return _table_html(comparison_overview(demo))


def evidence_html(demo: Mapping[str, Any]) -> str:
    """Render the evidence tables and data-backed charts in static HTML."""
    esc = html.escape
    output: list[str] = []
    for index, (title, notes, tables) in enumerate(report_sections(demo)):
        output.append(f"<section><h2>{esc(title)}</h2>")
        output.extend(f"<p>{esc(note)}</p>" for note in notes)
        if index:
            output.append(_telemetry_figures(demo["scenarios"][index - 1]))
        output.extend(_table_html(table) for table in tables if table[2])
        output.append("</section>")
    return "".join(output)
