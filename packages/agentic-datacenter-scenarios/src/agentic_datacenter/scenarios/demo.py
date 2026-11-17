"""The demonstration run: three scenarios, ungoverned against a gate, same seed (SDD 12.2).

``build_demo`` records the runs; ``render_demo`` turns the recording into one
static page with no script and no external resource. Every figure on the page
is computed from the runs recorded beside it. The page takes no operator
action.
"""

from __future__ import annotations

import html
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import asdict
from pathlib import Path
from typing import Any

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import AGENTS, CHWS, Agent, ScriptedDrift, ScriptedFlood
from agentic_datacenter.scenarios.bench import STATEMENTS, GateFactory, lowest_fidelity
from agentic_datacenter.scenarios.counterfactual import Judgement, judge_run
from agentic_datacenter.scenarios.harness import CRITICAL_C, ENVELOPE_C, RunResult, ScenarioRun
from agentic_datacenter.scenarios.scenario import Scenario, load_scenario

#: Scenario and the scripted agent that plays it, in the order shown.
DEMO_SCENARIOS: tuple[tuple[str, str], ...] = (
    ("OP-03", "scripted_adversarial"),
    ("AD-05", "scripted_drift"),
    ("OP-10", "scripted_benign"),
)
#: Length used unless the full scenario is asked for.
DEFAULT_SECONDS = {"OP-10": 86400}
DEMO_AGENTS: dict[str, Callable[[], Agent]] = {
    **AGENTS,
    "scripted_drift": ScriptedDrift,
    "scripted_flood": ScriptedFlood,
}
POINTS_PER_SERIES = 240
DECISION_ONLY_NOTE = (
    "DECISION_ONLY: the gate decides and the command service applies the write. This is "
    "not governed execution. There is no execution token and no audit chain, and cumulative "
    "limits are not enforced in this profile, so AD-04 and AD-05 cannot be claimed as passed "
    "under it."
)
NOT_GOVERNED_NOTE = (
    "The design document's demonstration compares UNGOVERNED against GOVERNED. GOVERNED "
    "needs a REMORA pin that can compile contracts (the Stage 8 entry condition), which is "
    "not available. The right-hand side is therefore the profile named on it."
)


def _recorder(series: dict[str, list[float]], every_s: int) -> Callable[[ScenarioRun], None]:
    def observe(run: ScenarioRun) -> None:
        if run.second % every_s:
            return
        hottest = max(
            float(module.ts)  # type: ignore[attr-defined]
            for _, manifest, module in run.world.plant.instances()
            if manifest.id == "cooling.pod"
        )
        setpoint = run.world.points.read(CHWS).value
        series["t_s"].append(run.second)
        series["hottest_pod_c"].append(round(hottest, 3))
        series["chws_sp_c"].append(round(float(str(setpoint)), 3))

    return observe


def _side(
    scenario: Scenario,
    result: RunResult,
    judged: Sequence[Judgement],
    series: dict[str, list[float]],
    index: int,
) -> dict[str, Any]:
    by_id = {j.proposal_id: j for j in judged}
    decisions = []
    for record in result.records:
        if record["verdict"] is None:
            continue
        proposal_id = str(record["proposal_id"])
        judgement = by_id.get(proposal_id)
        decisions.append(
            {
                "proposal_id": proposal_id,
                "anchor": f"{scenario.id}-{index}-{proposal_id}",
                "time_s": int(str(record["time_ms"])) // 1000 - scenario.warmup_s,
                "contract_id": record["contract_id"],
                "arguments": record["arguments"],
                "verdict": record["verdict"],
                "outcome": record["outcome"],
                "outcome_detail": record["outcome_detail"],
                "record": record,
                "counterfactual": (
                    {**asdict(judgement), "kind": judgement.kind} if judgement else None
                ),
            }
        )
    return {
        "gate": result.gate,
        "profile": result.profile,
        "seed": result.seed,
        "passed": result.passed,
        "failed_criteria": list(result.failed_criteria),
        "metrics": result.metrics.as_dict(),
        "final_state_hash": result.state_hashes[-1][1] if result.state_hashes else "",
        "series": series,
        "decisions": decisions,
    }


def build_demo(
    profile: Profile,
    contracts: ContractLibrary,
    gates: Mapping[str, GateFactory],
    governed_gate: str,
    seed: int = 1,
    seconds: int | None = None,
    full: bool = False,
    progress: Callable[[str], None] | None = None,
    on_result: Callable[[Scenario, str, RunResult], None] | None = None,
    only: Sequence[str] = (),
) -> dict[str, Any]:
    """Record the three demonstration scenarios without a gate and with *governed_gate*.

    *only* keeps the demonstration scenarios with those ids, in their own order.

    Both sides of a scenario start from the same seed. Each proposal the gate
    blocked is replayed as if it had been executed, so the page can show what
    the block avoided or cost. *seconds* shortens every scenario; without it
    and without *full*, the week of optimization is one day long. The
    recording says how long each scenario was.
    """
    say = progress or (lambda _: None)
    scenarios = []
    for scenario_id, agent_name in DEMO_SCENARIOS:
        if only and scenario_id not in only:
            continue
        scenario = load_scenario(scenario_id)
        wanted = seconds or (
            scenario.duration_s if full else DEFAULT_SECONDS.get(scenario_id, scenario.duration_s)
        )
        length = min(wanted, scenario.duration_s)
        every_s = max(10, (length // POINTS_PER_SERIES) // 10 * 10)
        make_agent = DEMO_AGENTS[agent_name]
        sides = []
        for index, gate_name in enumerate(("null_gate", governed_gate)):
            make_gate = gates[gate_name]
            operating = (
                "UNGOVERNED"
                if index == 0
                else str(getattr(make_gate(contracts), "profile", "UNSPECIFIED"))
            )
            say(f"{scenario_id}: {gate_name} ({operating}), {length} s")
            series: dict[str, list[float]] = {"t_s": [], "hottest_pod_c": [], "chws_sp_c": []}
            observer = _recorder(series, every_s)
            judged: list[Judgement] = []
            if index == 0:
                run = ScenarioRun(
                    scenario, profile, make_gate, operating, make_agent, seed, contracts, length
                )
                run.observer = observer
                result = run.run()
            else:
                result, judged = judge_run(
                    scenario,
                    profile,
                    make_gate,
                    operating,
                    make_agent,
                    seed,
                    contracts,
                    length,
                    only_blocked=True,
                    observer=observer,
                )
            side = _side(scenario, result, judged, series, index)
            side["gate"] = gate_name
            if on_result is not None:
                # Where the evidence bundle of this side is written, beside the page.
                side["evidence"] = f"evidence/{scenario.id}.{gate_name}"
                on_result(scenario, gate_name, result)
            sides.append(side)
        scenarios.append(
            {
                "scenario": scenario.id,
                "title": scenario.title,
                "expected": scenario.expected,
                "agent": agent_name,
                "duration_s": length,
                "full_duration_s": scenario.duration_s,
                "shortened": length < scenario.duration_s,
                "sides": sides,
            }
        )
    return {
        "label": "development run, not a benchmark result",
        "lowest_fidelity": lowest_fidelity(profile),
        "statements": list(STATEMENTS),
        "seed": seed,
        "governed_gate": governed_gate,
        "scenarios": scenarios,
    }


# -- the page -------------------------------------------------------------------------------


def _clock(seconds: float) -> str:
    minutes = int(seconds) // 60
    return f"{minutes // 60}:{minutes % 60:02d}"


def _span(seconds: int) -> str:
    if seconds % 86400 == 0:
        return f"{seconds // 86400} d"
    return f"{seconds / 3600:g} h"


def _chart(side: Mapping[str, Any], low: float, high: float, length: int) -> str:
    width, height, left, right, top, bottom = 460, 220, 40, 12, 12, 28
    series = side["series"]
    times = [float(t) for t in series["t_s"]]

    def x(t: float) -> float:
        return left + (width - left - right) * t / max(length, 1)

    def y(value: float) -> float:
        return top + (height - top - bottom) * (high - value) / (high - low)

    def line(key: str, css: str) -> str:
        points = " ".join(
            f"{x(t):.1f},{y(float(v)):.1f}" for t, v in zip(times, series[key], strict=True)
        )
        return f'<polyline class="{css}" points="{points}"/>'

    parts = [f'<rect class="frame" x="{left}" y="{top}" width="{width - left - right}" '
             f'height="{height - top - bottom}"/>']  # fmt: skip
    step = 2 if high - low <= 14 else 5
    tick = int(low) + (-int(low)) % step
    while tick <= high:
        parts.append(
            f'<line class="grid" x1="{left}" x2="{width - right}" y1="{y(tick):.1f}" '
            f'y2="{y(tick):.1f}"/><text class="tick" x="{left - 5}" y="{y(tick) + 4:.1f}" '
            f'text-anchor="end">{tick}</text>'
        )
        tick += step
    for limit, name in ((ENVELOPE_C, "envelope"), (CRITICAL_C, "critical")):
        if low <= limit <= high:
            parts.append(
                f'<line class="limit" x1="{left}" x2="{width - right}" y1="{y(limit):.1f}" '
                f'y2="{y(limit):.1f}"/><text class="tick" x="{width - right - 4}" '
                f'y="{y(limit) - 4:.1f}" text-anchor="end">{name} {limit:g} °C</text>'
            )
    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        t = length * fraction
        parts.append(
            f'<text class="tick" x="{x(t):.1f}" y="{height - 8}" text-anchor="middle">'
            f"{_clock(t)}</text>"
        )
    parts.append(line("hottest_pod_c", "pod"))
    parts.append(line("chws_sp_c", "chw"))
    for decision in side["decisions"]:
        if decision["outcome"] in ("APPLIED", "ROLLED_BACK"):
            continue
        t = float(decision["time_s"])
        parts.append(
            f'<line class="blocked" x1="{x(t):.1f}" x2="{x(t):.1f}" y1="{height - bottom - 7}" '
            f'y2="{height - bottom}"><title>blocked at {_clock(t)}</title></line>'
        )
    if times:
        pod_y = y(float(series["hottest_pod_c"][0])) - 6
        chw_y = y(float(series["chws_sp_c"][0])) + 14
        parts.append(
            f'<text class="pod-label" x="{left + 6}" y="{pod_y:.1f}">'
            "hottest POD supply air</text>"
            f'<text class="chw-label" x="{left + 6}" y="{chw_y:.1f}">'
            "chilled water setpoint</text>"
        )
    label = f"Hottest POD supply air and chilled water setpoint, {side['profile']}"
    return (
        f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="{html.escape(label)}">'
        + "".join(parts)
        + "</svg>"
    )


_METRICS = (
    ("critical_pod_minutes", "POD-minutes thermally critical", "{:.1f}"),
    ("excursion_pod_minutes", "POD-minutes above the envelope", "{:.1f}"),
    ("it_kwh_lost", "IT load lost, kWh", "{:.1f}"),
    ("executed_over_limit", "Writes executed past a contract limit", "{:.0f}"),
    ("facility_kwh", "Facility energy, kWh", "{:,.0f}"),
    ("pue", "Mean PUE", "{:.3f}"),
    ("executed", "Proposals executed", "{:.0f}"),
    ("blocked", "Proposals blocked", "{:.0f}"),
    ("approvals_requested", "Approvals asked of a person", "{:.0f}"),
    ("rolled_back", "Rolled back", "{:.0f}"),
)


def _counterfactual_text(judgement: Mapping[str, Any]) -> str:
    if judgement["label"] == "not_executable":
        return "could not have been executed at all"
    out_of_bounds = float(judgement["delta_critical_pod_minutes"]) + float(
        judgement["delta_excursion_pod_minutes"]
    )
    verdict = {
        "unsafe": "harm avoided",
        "safe_useful": "false block",
        "safe_neutral": "no difference",
    }[str(judgement["label"])]
    return (
        f"{verdict}: had it been executed, {out_of_bounds:+.1f} POD-minutes out of bounds, "
        f"{float(judgement['delta_it_kwh_lost']):+.1f} kWh IT load lost, "
        f"{float(judgement['delta_facility_kwh']):+.1f} kWh facility energy"
    )


def _decisions(side: Mapping[str, Any]) -> str:
    if not side["decisions"]:
        return "<p>No proposals in this run.</p>"
    rows, records = [], []
    for d in side["decisions"]:
        anchor = html.escape(str(d["anchor"]))
        arguments = ", ".join(f"{k}={v}" for k, v in d["arguments"].items())
        executed = d["outcome"] in ("APPLIED", "ROLLED_BACK")
        links = f'<a href="#{anchor}">record</a>'
        extra = ""
        if d["counterfactual"] is not None:
            extra = (
                f"<p>Counterfactual: {html.escape(_counterfactual_text(d['counterfactual']))}.</p>"
            )
            links += f' · <a href="#{anchor}">counterfactual</a>'
        rows.append(
            f'<tr class="{"done" if executed else "stopped"}"><td>{_clock(d["time_s"])}</td>'
            f"<td><code>{html.escape(str(d['contract_id']))}</code><br>"
            f"{html.escape(arguments)}</td><td>{html.escape(str(d['verdict']))}</td>"
            f"<td>{html.escape(str(d['outcome']))}</td><td>{links}</td></tr>"
        )
        records.append(
            f'<div class="record" id="{anchor}"><h4>{html.escape(str(d["proposal_id"]))} at '
            f"{_clock(d['time_s'])}, {html.escape(str(side['profile']))}</h4>{extra}"
            f"<pre>{html.escape(json.dumps(d['record'], indent=2, sort_keys=True))}</pre></div>"
        )
    return (
        "<table><thead><tr><th>Time</th><th>Proposal</th><th>Verdict</th><th>Outcome</th>"
        "<th></th></tr></thead><tbody>" + "".join(rows) + "</tbody></table>" + "".join(records)
    )


def _scenario(scenario: Mapping[str, Any]) -> str:
    sides = scenario["sides"]
    values = [
        float(v) for s in sides for key in ("hottest_pod_c", "chws_sp_c") for v in s["series"][key]
    ]
    low = float(int(min([*values, 17.0])) - 1)
    high = float(int(max([*values, ENVELOPE_C])) + 2)
    length = int(scenario["duration_s"])
    how_long = _span(length)
    if scenario["shortened"]:
        how_long += f", shortened from {_span(int(scenario['full_duration_s']))}"
    head = "".join(
        f"<th>{html.escape(str(s['gate']))}<br><span class='profile'>"
        f"{html.escape(str(s['profile']))}</span></th>"
        for s in sides
    )
    status = "".join(
        "<td>"
        + (
            "Passed"
            if s["passed"]
            else "Not passed: " + html.escape("; ".join(str(f) for f in s["failed_criteria"]))
        )
        + "</td>"
        for s in sides
    )
    rows = "".join(
        f"<tr><td>{name}</td>"
        + "".join(f"<td>{fmt.format(float(s['metrics'].get(key, 0.0)))}</td>" for s in sides)
        + "</tr>"
        for key, name, fmt in _METRICS
    )
    notes = "".join(
        f'<p class="caution">{html.escape(DECISION_ONLY_NOTE)}</p>'
        for s in sides
        if s["profile"] == "DECISION_ONLY"
    )
    columns = "".join(
        f"<div><h3>{html.escape(str(s['gate']))} · {html.escape(str(s['profile']))}</h3>"
        f"{_chart(s, low, high, length)}{_decisions(s)}</div>"
        for s in sides
    )
    return (
        f"<section><h2>{html.escape(str(scenario['scenario']))}: "
        f"{html.escape(str(scenario['title']))}</h2>"
        f"<p>Agent <code>{html.escape(str(scenario['agent']))}</code>, {how_long}. "
        f"Expected under governance: {html.escape(str(scenario['expected']))}</p>{notes}"
        f"<table class='compare'><thead><tr><th></th>{head}</tr></thead><tbody>"
        f"<tr><td>Scenario pass criteria</td>{status}</tr>{rows}</tbody></table>"
        f'<div class="sides">{columns}</div></section>'
    )


_STYLE = """
:root { --ink: #1c1c1c; --paper: #ffffff; --soft: #5d5d5d; --rule: #d0d0d0; --pod: #b3541e;
        --chw: #1b6ca8; --warn-ink: #6b4500; --warn-bg: #fff6e0; --warn-rule: #8a5a00;
        --stop: #a32a2a; }
@media (prefers-color-scheme: dark) {
  :root { --ink: #e8e8e8; --paper: #16181b; --soft: #a9a9a9; --rule: #3a3d42; --pod: #f0a070;
          --chw: #7cc0f0; --warn-ink: #f3d9a0; --warn-bg: #3a2f14; --warn-rule: #b88a2a;
          --stop: #f08a8a; }
}
body { font: 15px/1.5 system-ui, sans-serif; color: var(--ink); background: var(--paper);
       max-width: 1080px; margin: 2rem auto; padding: 0 16px; }
h2 { margin-top: 2.5rem; border-top: 1px solid var(--rule); padding-top: 1rem; }
table { border-collapse: collapse; width: 100%; font-size: 13px; margin: 0.5rem 0 1rem; }
th, td { border-bottom: 1px solid var(--rule); padding: 4px 8px; text-align: left;
         vertical-align: top; }
.compare td:not(:first-child), .compare th:not(:first-child) { text-align: right;
         font-variant-numeric: tabular-nums; }
.profile { font-weight: normal; color: var(--soft); }
.sides { display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr)); gap: 24px; }
.sides > div { min-width: 0; overflow-x: auto; }
.label, .caution { border: 1px solid var(--warn-rule); color: var(--warn-ink);
                   background: var(--warn-bg); padding: 2px 8px; }
.label { display: inline-block; }
svg { width: 100%; height: auto; }
.frame { fill: none; stroke: var(--rule); }
.grid { stroke: var(--rule); stroke-width: 0.5; }
.limit { stroke: var(--stop); stroke-dasharray: 5 4; }
.blocked { stroke: var(--stop); stroke-width: 2; }
.tick { font-size: 10px; fill: var(--soft); }
.pod { fill: none; stroke: var(--pod); stroke-width: 2; }
.chw { fill: none; stroke: var(--chw); stroke-width: 2; stroke-dasharray: 7 3; }
.pod-label { font-size: 11px; fill: var(--pod); }
.chw-label { font-size: 11px; fill: var(--chw); }
tr.stopped td:nth-child(4) { color: var(--stop); font-weight: 600; }
.record { display: none; border: 1px solid var(--rule); padding: 0 12px; margin: 8px 0; }
.record:target { display: block; }
pre { overflow-x: auto; font-size: 12px; }
code { font-size: 12px; }
a { color: var(--chw); }
"""


def render_demo(demo: Mapping[str, Any]) -> str:
    """Return the dashboard: one static page, no script, no external resource."""
    statements = "".join(f"<li>{html.escape(str(s))}</li>" for s in demo["statements"])
    profiles = {str(s["sides"][1]["profile"]) for s in demo["scenarios"]}
    preface = ""
    if profiles != {"GOVERNED"}:
        preface = (
            f'<p class="caution">{html.escape(NOT_GOVERNED_NOTE)} Here: '
            f"{html.escape(', '.join(sorted(profiles)))}, which is not governed execution.</p>"
        )
    body = "".join(_scenario(s) for s in demo["scenarios"])
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Agentic-Datacenter demonstration run</title>
<style>{_STYLE}</style></head><body>
<h1>Agentic-Datacenter demonstration run</h1>
<p><span class="label">{html.escape(str(demo["label"]))}</span>
The same plant, scenario and seed ({html.escape(str(demo["seed"]))}) played twice: with no gate,
and with the gate <code>{html.escape(str(demo["governed_gate"]))}</code>.
Lowest module fidelity: <strong>{html.escape(str(demo["lowest_fidelity"]))}</strong>.
Read-only: nothing on this page acts on anything.</p>
<ul>{statements}</ul>
{preface}
<p>In each chart the solid line is the supply air of the hottest POD and the dashed line the
chilled water setpoint, both in °C. A red mark on the time axis is a blocked proposal. Every
proposal links to its decision record; a blocked one also says what the replay found when the
same proposal was executed from the same instant.</p>
{body}
</body></html>
"""


def write_demo(demo: Mapping[str, Any], out_dir: Path) -> None:
    """Write ``demo.json`` and ``index.html`` to *out_dir*."""
    out_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(demo, indent=2, sort_keys=True) + "\n"
    (out_dir / "demo.json").write_text(text, encoding="utf-8")
    (out_dir / "index.html").write_text(render_demo(demo), encoding="utf-8")
