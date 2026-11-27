"""What the grid sees of a facility through a disturbance (ADR 0044).

A system operator's connection requirements say what a large consumer must do
when the voltage dips: stay connected, and be back at its consumption within
a time. A file in ``grid/`` holds one such set of requirements, with the place
each value was read. This module plays the dips of a file against a facility
and reports what its incomers drew, before, during and after.

It is a check of the plant, with no agent and no gate, and it is no part of
the benchmark. It reads the model at its own step of 100 ms and says so: a
time closer to a limit than the model can tell is reported as that, and not
as met or not met.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.core.scheduler import Kernel

from .plant import BuiltinPlant

SCHEMA = "agentic_datacenter.grid-requirements/1"
REPORT_SCHEMA = "agentic_datacenter.grid-check/1"
STATUSES = ("proposed", "recommended", "in_force")

#: Simulated seconds run before a disturbance, so the plant is in normal operation.
SETTLE_S = 300
#: Simulated seconds watched after the voltage is back.
WATCH_S = 120
#: Simulated seconds a voltage at the edge of the continuous range is held.
HOLD_S = 60
#: How far the draw may move and still count as unchanged, as a share of the draw before.
UNCHANGED = 0.05
#: Slack on a share read from a file, for arithmetic on floating-point numbers.
SLACK = 1e-3
#: Retained voltages tried against a curve, besides the levels the curve itself holds.
TRIED_PU = (0.0, 0.5, 0.7, 0.85)
#: The longest dip tried against a curve, in milliseconds.
LONGEST_MS = 3000

MET, NOT_MET, TOO_CLOSE, MEASURED = "met", "not met", "too close to tell", "measured only"

#: What the model cannot show, said on every report.
MODEL_LIMITS = (
    "The model steps every 100 ms. A dip is a step in voltage; nothing shorter is represented.",
    "The incomer has no source impedance: the facility's load does not move the grid's voltage.",
    "A UPS goes to battery and comes back in one step, and recharges at a fixed rate. "
    "A real one may wait, or walk its load in.",
    "Inside its input range a UPS draws the same power at any voltage. The current that "
    "takes at a low voltage is not limited, so widening the range shows what a UPS that "
    "can do it would give, not that one can.",
    "The facility is generic and not calibrated against a real one. A result says how "
    "this model behaves, not how a site does.",
)


@dataclass(frozen=True)
class Level:
    """One level of recovery a requirement asks for."""

    name: str
    min_share: float
    max_share: float | None
    within_s: float | None


@dataclass(frozen=True)
class Requirements:
    """One set of connection requirements, as read from a file in ``grid/``."""

    id: str
    data: Mapping[str, Any]
    curve: tuple[tuple[int, float], ...] | None
    dips: tuple[tuple[float, int], ...]
    back_pu: float
    levels: tuple[Level, ...]
    continuous: tuple[float, float] | None
    ramp_limit: float | None
    ramp_mw_per_min: float | None = None


def _is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def _is_whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def problems(data: object) -> list[str]:
    """Return what is wrong with a requirements file's content; empty when it can be used."""
    if not isinstance(data, Mapping):
        return ["the file is not a mapping"]
    found: list[str] = []
    if data.get("schema") != SCHEMA:
        found.append(f"schema must be {SCHEMA}")
    for key in ("id", "jurisdiction", "authority", "status_note", "read_on", "applies_to"):
        if not isinstance(data.get(key), str) or not data[key].strip():
            found.append(f"{key} must be text")
    if data.get("status") not in STATUSES:
        found.append(f"status must be one of {', '.join(STATUSES)}")
    source = data.get("source")
    if not isinstance(source, Mapping) or not all(
        isinstance(source.get(k), str) and source[k].strip()
        for k in ("title", "publisher", "published", "url", "sections")
    ):
        found.append("source must give title, publisher, published, url and sections")
    elif not str(source["url"]).startswith("https://"):
        found.append("source.url must be an https address")

    ride = data.get("ride_through") or {}
    curve = ride.get("curve_ms_pu") if isinstance(ride, Mapping) else None
    if not isinstance(ride, Mapping):
        found.append("ride_through must be a mapping")
    elif curve is not None:
        ok = isinstance(curve, list) and len(curve) >= 2 and all(
            isinstance(p, list) and len(p) == 2 and _is_whole(p[0]) and _is_number(p[1])
            and p[0] >= 0 and 0.0 <= p[1] <= 1.0
            for p in curve
        )  # fmt: skip
        if not ok:
            found.append("ride_through.curve_ms_pu must be points of [whole ms, pu]")
        elif any(a[0] > b[0] for a, b in zip(curve, curve[1:], strict=False)):
            found.append("ride_through.curve_ms_pu must go forward in time")
    if isinstance(ride, Mapping):
        dips = ride.get("dips_pu_ms") or []
        if not isinstance(dips, list):
            found.append("ride_through.dips_pu_ms must be a list of [pu, ms]")
            dips = []
        for dip in dips:
            if not (
                isinstance(dip, list) and len(dip) == 2 and _is_number(dip[0])
                and 0.0 <= dip[0] < 1.0 and _dip_length_ok(dip[1])
            ):  # fmt: skip
                found.append("ride_through.dips_pu_ms must be [pu, ms], ms a multiple of 100")

    recovery = data.get("recovery")
    if recovery is not None:
        levels = recovery.get("levels") if isinstance(recovery, Mapping) else None
        if not isinstance(recovery, Mapping) or not _is_number(recovery.get("voltage_back_pu")):
            found.append("recovery.voltage_back_pu must be a number")
        if not isinstance(levels, list) or not levels:
            found.append("recovery.levels must list at least one level")
        else:
            for level in levels:
                if not (
                    isinstance(level, Mapping) and isinstance(level.get("name"), str)
                    and _is_number(level.get("min_share"))
                    and (level.get("max_share") is None or _is_number(level["max_share"]))
                    and (level.get("within_s") is None or _is_number(level["within_s"]))
                ):  # fmt: skip
                    found.append("a recovery level needs name, min_share, max_share and within_s")
                elif level.get("within_s") is not None and not 0 < level["within_s"] <= WATCH_S / 2:
                    found.append(
                        f"a recovery time is more than 0 and at most {WATCH_S // 2} s:"
                        f" the facility is watched for {WATCH_S} s"
                    )
    continuous = data.get("continuous")
    if continuous is not None and not (
        isinstance(continuous, Mapping) and _is_number(continuous.get("low_pu"))
        and _is_number(continuous.get("high_pu"))
        and 0.0 < continuous["low_pu"] <= 1.0 <= continuous["high_pu"]
    ):  # fmt: skip
        found.append("continuous must give low_pu and high_pu around 1.0")
    ramp = data.get("ramp")
    if ramp is not None and not (
        isinstance(ramp, Mapping)
        and all(
            ramp.get(key) is None or _is_number(ramp[key])
            for key in ("limit_share_per_s", "limit_mw_per_min", "max_step_mw")
        )
    ):
        found.append("ramp limits must be numbers or null")
    low = data.get("low_frequency")
    if low is not None and not (
        isinstance(low, Mapping)
        and (low.get("threshold_hz") is None or _is_number(low["threshold_hz"]))
        and isinstance(low.get("note"), str)
    ):
        found.append("low_frequency must give threshold_hz, a number or null, and a note")
    left_out = data.get("not_checked")
    if not isinstance(left_out, list) or not all(
        isinstance(row, Mapping) and isinstance(row.get("what"), str)
        and isinstance(row.get("why"), str)
        for row in left_out
    ):  # fmt: skip
        found.append("not_checked must list what is left out and why")
    return found


def _dip_length_ok(ms: object) -> bool:
    return isinstance(ms, int) and not isinstance(ms, bool) and ms > 0 and ms % 100 == 0


def load_requirements(path: Path) -> Requirements:
    """Read one requirements file.

    Raises:
        ValueError: If the file cannot be used; the message lists every problem.
    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    found = problems(data)
    if found:
        raise ValueError(f"{path}: " + "; ".join(found))
    ride = data.get("ride_through") or {}
    curve = ride.get("curve_ms_pu")
    recovery = data.get("recovery") or {}
    continuous = data.get("continuous")
    return Requirements(
        id=data["id"],
        data=data,
        curve=None if curve is None else tuple((int(t), float(v)) for t, v in curve),
        dips=tuple((float(v), int(t)) for v, t in ride.get("dips_pu_ms") or ()),
        back_pu=float(recovery.get("voltage_back_pu", 0.9)),
        levels=tuple(
            Level(
                str(row["name"]),
                float(row["min_share"]),
                None if row.get("max_share") is None else float(row["max_share"]),
                None if row.get("within_s") is None else float(row["within_s"]),
            )
            for row in recovery.get("levels", ())
        ),
        continuous=(
            None
            if continuous is None
            else (float(continuous["low_pu"]), float(continuous["high_pu"]))
        ),
        ramp_limit=(
            None
            if (data.get("ramp") or {}).get("limit_share_per_s") is None
            else float(data["ramp"]["limit_share_per_s"])
        ),
        ramp_mw_per_min=(
            None
            if (data.get("ramp") or {}).get("limit_mw_per_min") is None
            else float(data["ramp"]["limit_mw_per_min"])
        ),
    )


def curve_at(curve: Sequence[tuple[int, float]], ms: float) -> float:
    """Return the curve's voltage at *ms*: the higher value where the curve steps."""
    if ms <= curve[0][0]:
        return max(v for t, v in curve if t == curve[0][0])
    if ms >= curve[-1][0]:
        return max(v for t, v in curve if t == curve[-1][0])
    at = [v for t, v in curve if t == ms]
    if at:
        return max(at)
    for (t0, v0), (t1, v1) in zip(curve, curve[1:], strict=False):
        if t0 < ms < t1:
            return v0 + (v1 - v0) * (ms - t0) / (t1 - t0)
    return curve[-1][1]


def dips_of(curve: Sequence[tuple[int, float]], step_ms: int = 100) -> list[tuple[float, int]]:
    """Return the longest rectangular dips that stay on or above *curve*, one per voltage.

    A dip holds one retained voltage and then returns to nominal. Each is as
    long as the curve allows in whole steps: the dips a facility must stay
    connected through, at the edge of what is asked.
    """
    top = curve[-1][1]
    levels = sorted({*TRIED_PU, *(v for _, v in curve)})
    dips = []
    for level in levels:
        if level >= top:
            continue
        ms = 0
        while ms + step_ms <= LONGEST_MS and all(
            level >= curve_at(curve, t) for t in range(0, ms + step_ms + 1, step_ms)
        ):
            ms += step_ms
        if ms:
            dips.append((level, ms))
    return dips


class _Run:
    """One facility in normal operation, ready for a disturbance."""

    def __init__(self, profile: Profile) -> None:
        self.kernel = Kernel(seed=1)
        self.plant = BuiltinPlant(profile, self.kernel)
        self.step_ms = self.kernel.clock.step_ms
        self.incomers, self.ups = [], []
        for name, manifest, module in self.plant.modules.instances():
            if manifest.id == "electrical.utility":
                self.incomers.append(name)
            elif manifest.id == "electrical.ups":
                self.ups.append(module)
        if not self.incomers:
            raise ValueError("the facility has no utility incomer to disturb")
        self.advance(SETTLE_S)
        self.before_kw = self.draw_kw()
        if self.before_kw <= 0.0:
            raise ValueError("the facility draws nothing from its incomers in normal operation")
        self.lost_before = self.lost_kwh()

    def steps(self, seconds: float) -> int:
        return round(seconds * 1000 / self.step_ms)

    def advance(self, seconds: float) -> None:
        for _ in range(self.steps(seconds)):
            self.kernel.step()

    def draw_kw(self) -> float:
        return float(sum(self.plant.harm().facility_in_kw))

    def served_kw(self) -> float:
        return float(sum(self.plant.harm().it_served_kw))

    def lost_kwh(self) -> float:
        return float(sum(self.plant.harm().it_kwh_lost))

    def on_battery(self) -> bool:
        return any(m.io["mode"] == "ON_BATTERY" for m in self.ups)  # type: ignore[attr-defined]

    def voltage(self, pu: float) -> None:
        for name in self.incomers:
            self.plant.inject(name, "set", {"voltage_pu": pu})

    def watch(self, steps: int) -> tuple[list[float], bool]:
        """Step *steps* times; return each draw as a share, and whether a UPS was on battery."""
        shares, battery = [], False
        for _ in range(steps):
            self.kernel.step()
            shares.append(self.draw_kw() / self.before_kw)
            battery = battery or self.on_battery()
        return shares, battery


def model_delay_s(profile: Profile) -> float:
    """Return how long the model takes to show a change of voltage in the incomers' draw.

    A change travels one module per step, down to the loads and back up. It is
    the model's own delay and no property of a facility, so a time is judged
    with it and without it.
    """
    run = _Run(profile)
    run.voltage(0.01)
    shares, _ = run.watch(run.steps(2.0))
    for index, share in enumerate(shares):
        if abs(share - 1.0) > 0.005:
            return index * run.step_ms / 1000
    return 0.0


def _back_after(shares: Sequence[float], level: Level, step_s: float) -> float | None:
    """Return the seconds until the draw is at *level* and stays there, or None if it never is."""
    high = float("inf") if level.max_share is None else level.max_share + SLACK
    last_out = -1
    for index, share in enumerate(shares):
        if not level.min_share - SLACK <= share <= high:
            last_out = index
    if last_out == len(shares) - 1:
        return None
    if last_out < 0:
        return 0.0  # it never left
    # The sample at index i is taken i + 1 steps after the voltage is back.
    return round((last_out + 2) * step_s, 3)


def _verdict(back_s: float | None, within_s: float | None, delay_s: float) -> str:
    if back_s is None:
        return NOT_MET
    if within_s is None:
        return MEASURED
    if back_s <= within_s:
        return MET
    return NOT_MET if back_s - delay_s > within_s else TOO_CLOSE


def _largest_change(shares: Sequence[float], window: int) -> float:
    """Return the largest change of the draw within *window* steps, as a share."""
    largest = 0.0
    for index, share in enumerate(shares):
        for later in shares[index + 1 : index + 1 + window]:
            largest = max(largest, abs(later - share))
    return largest


def _swing(shares: Sequence[float], window: int) -> float:
    """Return the largest change of the draw within *window* steps, from a sliding range."""
    largest = 0.0
    for start in range(max(1, len(shares) - window + 1)):
        part = shares[start : start + window]
        largest = max(largest, max(part) - min(part))
    return largest


def run_dip(
    profile: Profile, retained_pu: float, ms: int, levels: Sequence[Level], delay_s: float
) -> dict[str, Any]:
    """Play one dip against the facility and return what its incomers drew."""
    run = _Run(profile)
    step_s = run.step_ms / 1000
    run.voltage(retained_pu)
    during, battery_during = run.watch(ms // run.step_ms)
    run.voltage(1.0)
    after, battery_after = run.watch(run.steps(WATCH_S))
    shown = after[run.steps(delay_s) :] or after
    return {
        "retained_pu": retained_pu,
        "ms": ms,
        "lowest_share": round(min([*during, *after]), 4),
        "highest_share_after": round(max(shown), 4),
        "largest_change_share_per_s": round(
            _largest_change([1.0, *during, *after], run.steps(1.0)), 4
        ),
        "largest_change_share_per_min": round(_swing([1.0, *during, *after], run.steps(60.0)), 4),
        "on_battery": battery_during or battery_after,
        "it_lost_kwh": round(run.lost_kwh() - run.lost_before, 6),
        "levels": [
            {
                "name": level.name,
                "min_share": level.min_share,
                "max_share": level.max_share,
                "within_s": level.within_s,
                "back_after_s": (back := _back_after(after, level, step_s)),
                "verdict": _verdict(back, level.within_s, delay_s),
            }
            for level in levels
        ],
    }


def run_hold(profile: Profile, pu: float) -> dict[str, Any]:
    """Hold the incomers at *pu* and return whether the facility went on as before."""
    run = _Run(profile)
    run.voltage(pu)
    shares, battery = run.watch(run.steps(HOLD_S))
    lost = run.lost_kwh() - run.lost_before
    steady = all(abs(share - 1.0) <= UNCHANGED for share in shares)
    return {
        "pu": pu,
        "held_s": HOLD_S,
        "lowest_share": round(min(shares), 4),
        "highest_share": round(max(shares), 4),
        "on_battery": battery,
        "it_lost_kwh": round(lost, 6),
        "verdict": MET if steady and not battery and lost == 0.0 else NOT_MET,
    }


def check(
    requirements: Requirements,
    profile: Profile,
    asked_dips: Sequence[tuple[float, int]] = (),
    ramp_limit: float | None = None,
    changed: Mapping[str, object] | None = None,
) -> dict[str, Any]:
    """Play a requirements file against a facility and return the report."""
    data = requirements.data
    base = _Run(profile)
    delay_s = model_delay_s(profile)
    dips = [
        *(("curve", v, t) for v, t in (dips_of(requirements.curve) if requirements.curve else ())),
        *(("file", v, t) for v, t in requirements.dips),
        *(("asked", v, t) for v, t in asked_dips),
    ]
    played = []
    for origin, retained, ms in dips:
        played.append(
            {"origin": origin, **run_dip(profile, retained, ms, requirements.levels, delay_s)}
        )
    holds = [run_hold(profile, pu) for pu in requirements.continuous or ()]

    limit = requirements.ramp_limit if ramp_limit is None else ramp_limit
    largest = max((dip["largest_change_share_per_s"] for dip in played), default=None)
    ramp: dict[str, Any] | None = None
    if largest is not None:
        ramp = {
            "largest_change_share_per_s": largest,
            "limit_share_per_s": limit,
            "verdict": MEASURED if limit is None else (MET if largest <= limit else NOT_MET),
            "note": (data.get("ramp") or {}).get("note"),
        }
        per_min = requirements.ramp_mw_per_min
        swing = max(dip["largest_change_share_per_min"] for dip in played)
        if per_min is not None and swing > 0.0:
            # An absolute limit says nothing of a small facility. What it does say is how
            # large a facility of this design may be before the same swing is over it.
            ramp["limit_mw_per_min"] = per_min
            ramp["largest_change_share_per_min"] = swing
            ramp["over_the_limit_above_mw"] = round(per_min / swing, 1)

    verdicts = [
        *(level["verdict"] for dip in played for level in dip["levels"]),
        *(hold["verdict"] for hold in holds),
        *([ramp["verdict"]] if ramp else []),
    ]
    return {
        "schema": REPORT_SCHEMA,
        "requirements": {
            key: data[key]
            for key in (
                "id",
                "jurisdiction",
                "authority",
                "status",
                "status_note",
                "source",
                "read_on",
                "applies_to",
            )
        },  # fmt: skip
        "facility": {
            "profile": profile.hash(),
            "changed": dict(changed or {}),
            "draw_kw": round(base.before_kw, 1),
            "it_kw": round(base.served_kw(), 1),
            "incomers": len(base.incomers),
        },
        "model": {"step_ms": base.step_ms, "delay_s": delay_s, "limits": list(MODEL_LIMITS)},
        "dips": played,
        "continuous": holds,
        "ramp": ramp,
        "ride_through_note": (data.get("ride_through") or {}).get("note"),
        "not_checked": list(data["not_checked"]),
        "summary": {
            verdict: verdicts.count(verdict) for verdict in (MET, NOT_MET, TOO_CLOSE, MEASURED)
        },
    }


def _pct(share: float) -> str:
    return f"{100 * share:.0f} %"


def render(report: Mapping[str, Any]) -> str:
    """Return the report as text for a terminal."""
    req, facility, model = report["requirements"], report["facility"], report["model"]
    source = req["source"]
    status = {
        "proposed": "PROPOSED, not in force",
        "recommended": "RECOMMENDED, not law",
        "in_force": "in force",
    }[req["status"]]
    lines = [
        f"{req['id']}: {req['jurisdiction']}, {req['authority']}",
        f"  Status: {status}. {' '.join(req['status_note'].split())}",
        f"  Source: {source['publisher']}, {source['title']} ({source['published']}),"
        f" {source['sections']}; read {req['read_on']}",
        f"  Applies to: {' '.join(req['applies_to'].split())}",
        "",
        f"Facility: draws {facility['draw_kw']:.0f} kW from {facility['incomers']} incomers,"
        f" {facility['it_kw']:.0f} kW of it IT load.",
    ]
    for name, value in facility["changed"].items():
        lines.append(f"  Changed for this check: {name} = {value}")
    lines.append(
        "  What follows is in shares of that draw, so it reads the same for a larger facility"
        " of this design."
    )
    if report["continuous"]:
        lines += ["", "Held at the edge of the continuous range:"]
        for hold in report["continuous"]:
            how = "went on as before" if hold["verdict"] == MET else "did not go on as before"
            battery = "; a UPS went to battery" if hold["on_battery"] else ""
            lines.append(
                f"  {hold['pu']:.2f} pu for {hold['held_s']} s: {how}"
                f" (draw {_pct(hold['lowest_share'])} to {_pct(hold['highest_share'])}{battery})"
                f"  [{hold['verdict']}]"
            )
    if report["dips"]:
        lines += ["", "Voltage dips:"]
    for dip in report["dips"]:
        where = {
            "curve": " (the longest the curve asks a facility to stay connected through)",
            "file": " (from the file)",
            "asked": " (asked for, not from the requirement)",
        }[dip["origin"]]
        carried = (
            "a UPS carried IT load on battery" if dip["on_battery"] else "no UPS went to battery"
        )
        lost = f"; {dip['it_lost_kwh']:.3f} kWh of IT load lost" if dip["it_lost_kwh"] else ""
        lines += [
            f"  {dip['retained_pu']:.2f} pu for {dip['ms']} ms{where}",
            f"    draw fell to {_pct(dip['lowest_share'])}; {carried}{lost}",
            f"    highest after: {_pct(dip['highest_share_after'])};"
            f" largest change within one second: {_pct(dip['largest_change_share_per_s'])}",
        ]
        for level in dip["levels"]:
            band = f"at least {_pct(level['min_share'])}" if level["max_share"] is None else (
                f"{_pct(level['min_share'])} to {_pct(level['max_share'])}"
            )  # fmt: skip
            asked = (
                "no time read" if level["within_s"] is None else f"within {level['within_s']:g} s"
            )
            took = (
                "never, in the two minutes watched" if level["back_after_s"] is None
                else f"after {level['back_after_s']:g} s"
            )  # fmt: skip
            lines.append(
                f"    back at {band}, {asked} ({level['name']}): {took}  [{level['verdict']}]"
            )
    if not report["dips"] and report["ride_through_note"]:
        lines += ["", f"No dip tried: {' '.join(report['ride_through_note'].split())}"]
    ramp = report["ramp"]
    if ramp:
        limit = (
            "no limit to hold it to" if ramp["limit_share_per_s"] is None
            else f"limit {_pct(ramp['limit_share_per_s'])} per second"
        )  # fmt: skip
        lines += [
            "",
            f"Ramping: the draw changed by up to {_pct(ramp['largest_change_share_per_s'])}"
            f" within one second; {limit}  [{ramp['verdict']}]",
        ]
        if ramp["note"]:
            lines.append(f"  {' '.join(ramp['note'].split())}")
        if ramp.get("limit_mw_per_min") is not None:
            lines.append(
                f"  Within a minute the draw changed by up to"
                f" {_pct(ramp['largest_change_share_per_min'])}. Against"
                f" {ramp['limit_mw_per_min']:g} MW a minute, a facility of this design drawing"
                f" more than {ramp['over_the_limit_above_mw']:g} MW would be over the limit;"
                f" this one draws {facility['draw_kw'] / 1000:.1f} MW."
            )
    lines += ["", "Not checked, and why:"]
    lines += [f"  - {row['what']}: {row['why']}" for row in report["not_checked"]]
    lines += [
        "",
        f"What this model can and cannot show (it shows a change of voltage in the draw after"
        f" {model['delay_s']:g} s of its own; a time is judged with that and without it):",
    ]
    lines += [f"  - {limit}" for limit in model["limits"]]
    summary = report["summary"]
    lines += [
        "",
        "Result: "
        + (", ".join(f"{n} {verdict}" for verdict, n in summary.items() if n) or "nothing tried")
        + ". Not a statement of compliance: a simulated facility, against requirements"
        f" that are {req['status'].replace('_', ' ')}.",
    ]
    return "\n".join(lines)
