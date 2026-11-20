"""Derived views of the plant for operators and for a governance gate.

Everything here is computed from the point database, so it has the quality of
the points it reads: with the supervisory network down these views are stale
too, and say so.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass

from agentic_datacenter.supervisory.points import PointDatabase, PointRecord

#: Alarm priorities (SDD 7.5): urgent 751 to 999, high 501 to 750, medium 500.
URGENT, HIGH, MEDIUM = 900, 600, 500
_PRIORITY = {
    "thermally_critical": URGENT,
    "alarm_lockout": URGENT,
    "leak_alarm": HIGH,
    "on_battery_alarm": HIGH,
    "dropped": URGENT,
    "thermal_trip": URGENT,
    "zone_mean_invalid": HIGH,
}
_SYSTEM = {
    "cooling.pod": "POD",
    "cooling.chw_plant": "CHW",
    "cooling.pump_station": "CHW",
    "cooling.tes": "CHW",
    "cooling.eroom": "PWR",
    "electrical.power_train": "PWR",
    "electrical.genset": "PWR",
    "electrical.ups": "PWR",
    "electrical.mv_switchgear": "MV",
    "electrical.it_load": "IT",
    "electrical.utility": "MV",
}
N_PLUS_1, N, BELOW_N = 2, 1, 0
LEVEL_NAMES = {N_PLUS_1: "N_PLUS_1", N: "N", BELOW_N: "BELOW_N"}


@dataclass(frozen=True)
class Alarm:
    """One active alarm."""

    tag: str
    priority: int
    system: str
    description: str
    quality: str


@dataclass(frozen=True)
class Redundancy:
    """How many units a system has usable, how many it needs, and what margin that is."""

    system: str
    available: int
    required: int
    level: int
    quality: str

    @property
    def level_name(self) -> str:
        """``N_PLUS_1``, ``N`` or ``BELOW_N``."""
        return LEVEL_NAMES[self.level]


def _level(available: int, required: int) -> int:
    if available > required:
        return N_PLUS_1
    return N if available == required else BELOW_N


def _worst(records: list[PointRecord]) -> str:
    return "good" if all(r.quality == "good" for r in records) else "stale"


#: Specific heat of air, kJ/(kg K), for the supply air cross-check.
AIR_CP = 1.006
#: How far the measured air temperature rise may differ from the one the IT power implies.
INCONSISTENCY_K = 2.0
NOTE = 100  # logged events and operator notes: below every alarm priority


class Overview:
    """Alarms, redundancy and energy, read from the point database."""

    def __init__(self, points: PointDatabase, notes: Sequence[str] = ()) -> None:
        """Create the views on *points*; *notes* are free-text entries shown with the alarms."""
        self._points = points
        self._notes = notes

    def inconsistent_pods(self) -> list[Alarm]:
        """Cross-check each POD's supply air reading against return air and IT power.

        Return air minus supply air must equal the heat released divided by
        the airflow. A supply reading that is biased breaks that balance by
        the size of the bias, whatever the zone sensors agree on among
        themselves (scenario AD-03).
        """
        out = []
        read = self._points.read
        for supply in self._points.find("cooling.pod", "supply_air_c"):
            pod = supply.tag.rsplit(".", 1)[0]
            load = pod.replace("cooling.pod", "electrical.it_load")
            if f"{load}.served_kw" not in self._points.tags():
                continue
            flow = float(read(f"{load}.airflow_kg_s").value) * AIR_CP
            if flow <= 0.0 or read(f"{pod}.fans_running").value is not True:
                continue
            heat = float(read(f"{load}.served_kw").value) + float(read(f"{pod}.fan_kw").value)
            measured = float(read(f"{pod}.return_air_c").value) - float(supply.value)
            if abs(measured - heat / flow) > INCONSISTENCY_K:
                out.append(
                    Alarm(
                        f"{pod}.supply_air_inconsistent",
                        HIGH,
                        "POD",
                        "Supply air reading disagrees with return air and IT power",
                        supply.quality,
                    )
                )
        return out

    def active_alarms(self) -> list[Alarm]:
        """Return every active alarm, most urgent first."""
        alarms = []
        for tag in self._points.tags():
            name, _, point = tag.rpartition(".")
            is_alarm = point.startswith("alarm_") or point in _PRIORITY
            if not is_alarm:
                continue
            record = self._points.read(tag)
            if record.value is True:
                module_id = name.split("[", 1)[0]
                priority = _PRIORITY.get(point, HIGH)
                alarms.append(
                    Alarm(
                        tag,
                        priority,
                        _SYSTEM.get(module_id, "OTHER"),
                        record.description,
                        record.quality,
                    )
                )
        for record in self._points.find("cooling.chw_plant", "ch1_state"):
            base = record.tag.rsplit(".", 1)[0]
            for n in (1, 2, 3):
                state = self._points.read(f"{base}.ch{n}_state")
                if state.value in ("TRIPPED", "LOCKED_OUT"):
                    alarms.append(
                        Alarm(state.tag, HIGH, "CHW", f"Chiller {n} {state.value}", state.quality)
                    )
        alarms += self.inconsistent_pods()
        quality, _ = self._points.freshness()
        alarms += [
            Alarm(f"note[{index}]", NOTE, "NOTE", text, quality)
            for index, text in enumerate(self._notes)
        ]
        return sorted(alarms, key=lambda a: (-a.priority, a.tag))

    def redundancy(self) -> dict[str, Redundancy]:
        """Return the redundancy of chillers, pumps and power trains."""
        out: dict[str, Redundancy] = {}
        read = self._points.read
        for load in self._points.find("cooling.chw_plant", "load_kw"):
            base = load.tag.rsplit(".", 1)[0]
            states = [read(f"{base}.ch{n}_state") for n in (1, 2, 3)]
            enabled = [read(f"{base}.ch{n}_enable") for n in (1, 2, 3)]
            usable = sum(
                1 for s, e in zip(states, enabled, strict=True)
                if e.value is True and s.value not in ("TRIPPED", "LOCKED_OUT")
            )  # fmt: skip
            each = read(f"{base}.unit_capacity_kw")
            unit_kw = float(each.value)
            needed = max(1, math.ceil(float(load.value) / unit_kw - 1e-9)) if unit_kw > 0.0 else 1
            quality = _worst([load, each, *states, *enabled])
            out["chillers"] = Redundancy(
                "chillers", usable, needed, _level(usable, needed), quality
            )
        for flow in self._points.find("cooling.pump_station", "flow_kg_s"):
            base = flow.tag.rsplit(".", 1)[0]
            pumps = [read(f"{base}.p{n}_running") for n in (1, 2, 3)]
            count = sum(1 for r in pumps if r.value is True)
            # Two duty pumps carry the design flow; with both running the third is the spare.
            spare = 1 if count == 2 else 0
            out["pumps"] = Redundancy(
                "pumps", count + spare, 2, _level(count + spare, 2), _worst([flow, *pumps])
            )
        trains = self._points.find("electrical.power_train", "state")
        if trains:
            healthy = sum(1 for t in trains if t.value == "ON_UTILITY")
            energized = 0
            for t in trains:
                base = t.tag.rsplit(".", 1)[0]
                closed = (
                    read(f"{base}.util_brk_closed").value is True
                    or read(f"{base}.gen_brk_closed").value is True
                )
                energized += 1 if closed else 0
            usable = healthy + (energized - healthy)
            out["trains"] = Redundancy(
                "trains", usable, len(trains) - 1, _level(healthy, len(trains) - 1), _worst(trains)
            )
        return out

    def energy(self) -> dict[str, float | str]:
        """Return power by system and the power usage effectiveness."""
        find = self._points.find
        it = find("electrical.it_load", "served_kw")
        incomers = [
            *find("electrical.mv_switchgear", "inc_1_kw"),
            *find("electrical.mv_switchgear", "inc_2_kw"),
        ]
        chillers = find("cooling.chw_plant", "power_kw")
        pumps = find("cooling.pump_station", "power_kw")
        fans = [*find("cooling.pod", "fan_kw"), *find("cooling.eroom", "fan_kw")]
        ups = find("electrical.ups", "loss_kw")
        it_kw = sum(float(r.value) for r in it)
        total = sum(float(r.value) for r in incomers)
        return {
            "it_kw": it_kw,
            "facility_kw": total,
            "chillers_kw": sum(float(r.value) for r in chillers),
            "pumps_kw": sum(float(r.value) for r in pumps),
            "fans_kw": sum(float(r.value) for r in fans),
            "ups_loss_kw": sum(float(r.value) for r in ups),
            "pue": total / it_kw if it_kw > 0.0 else 0.0,
            "quality": _worst([*it, *incomers, *chillers, *pumps, *fans, *ups]),
        }
