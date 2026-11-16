"""The historian (SDD 7.5): real-time values every second, energy every fifteen minutes.

It records what the point database shows, with its quality, so a stale value
is recorded as stale. What it holds is derived from the run and is not part of
the simulation state or its hash: the same run always gives the same history.
Both retentions are configurable.

Storage is in memory. Writing the history to files belongs to the evidence
bundle (ADR 0009).
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass

from agentic_datacenter.core.io import PointValue
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.supervisory.overview import Overview
from agentic_datacenter.supervisory.points import PointDatabase

SAMPLE_MS = 1000
ENERGY_INTERVAL_S = 900
_SYSTEMS = ("it", "facility", "chillers", "pumps", "fans", "ups_loss")
_REALTIME = {
    "cooling.pod": ("supply_air_c",),
    "cooling.chw_plant": ("chws_sp_c", "power_kw"),
    "electrical.it_load": ("served_kw",),
    "electrical.mv_switchgear": ("inc_1_kw", "inc_2_kw"),
}


@dataclass(frozen=True)
class Sample:
    """One recorded value."""

    time_ms: int
    value: PointValue
    quality: str


def default_realtime_tags(points: PointDatabase) -> list[str]:
    """Return the critical points recorded every second unless a run says otherwise."""
    return sorted(
        record.tag
        for module_id, names in _REALTIME.items()
        for name in names
        for record in points.find(module_id, name)
    )


class Historian:
    """Keeps a ring of real-time samples per tag and a list of energy records."""

    def __init__(
        self,
        kernel: Kernel,
        points: PointDatabase,
        realtime_tags: Sequence[str] | None = None,
        retention_s: int = 3600,
        energy_retention_records: int = 96 * 35,
    ) -> None:
        """Start recording *realtime_tags* (default: :func:`default_realtime_tags`)."""
        self._kernel, self._points = kernel, points
        self._overview = Overview(points)
        self.realtime_tags = list(
            realtime_tags if realtime_tags is not None else default_realtime_tags(points)
        )
        self._rings: dict[str, deque[Sample]] = {
            tag: deque(maxlen=retention_s) for tag in self.realtime_tags
        }
        self._energy: deque[dict[str, float | int | str]] = deque(maxlen=energy_retention_records)
        self._sums = dict.fromkeys(_SYSTEMS, 0.0)
        self._worst = "good"
        self._last_ms = -1
        kernel.add_task("supervisory.historian", self._sample, period_ms=SAMPLE_MS)

    def _cut_back(self, now: int) -> None:
        """Forget what was recorded after *now*: the run has been restored to an earlier time."""
        for ring in self._rings.values():
            while ring and ring[-1].time_ms >= now:
                ring.pop()
        while self._energy and int(self._energy[-1]["time_ms"]) >= now:
            self._energy.pop()
        # The interval in progress is recomputed from its start; what was summed is unknown.
        self._sums = dict.fromkeys(_SYSTEMS, 0.0)
        self._worst = "restored"

    def _sample(self) -> None:
        now = self._kernel.clock.now_ms
        if now <= self._last_ms:
            self._cut_back(now)
        self._last_ms = now
        if now > 0 and now % (ENERGY_INTERVAL_S * 1000) == 0:
            it, facility = self._sums["it"], self._sums["facility"]
            self._energy.append(
                {
                    "time_ms": now,
                    "interval_s": ENERGY_INTERVAL_S,
                    **{f"{system}_kwh": self._sums[system] for system in _SYSTEMS},
                    "pue": facility / it if it > 0.0 else 0.0,
                    "quality": self._worst,
                }
            )
            self._sums = dict.fromkeys(_SYSTEMS, 0.0)
            self._worst = "good"
        for tag, ring in self._rings.items():
            record = self._points.read(tag)
            ring.append(Sample(now, record.value, record.quality))
        energy = self._overview.energy()
        hours = SAMPLE_MS / 3_600_000
        for system in _SYSTEMS:
            self._sums[system] += float(energy[f"{system}_kw"]) * hours
        if energy["quality"] != "good" and self._worst == "good":
            self._worst = str(energy["quality"])

    def history(
        self, tag: str, from_ms: int | None = None, to_ms: int | None = None
    ) -> list[Sample]:
        """Return the samples of *tag* between *from_ms* and *to_ms*, both included.

        Raises:
            KeyError: If the tag is not recorded.
        """
        if tag not in self._rings:
            raise KeyError(f"{tag} is not recorded by the historian")
        low = from_ms if from_ms is not None else 0
        return [
            s
            for s in self._rings[tag]
            if s.time_ms >= low and (to_ms is None or s.time_ms <= to_ms)
        ]

    def energy_records(self, from_ms: int | None = None) -> list[dict[str, float | int | str]]:
        """Return the fifteen-minute energy records from *from_ms* on."""
        return [dict(r) for r in self._energy if from_ms is None or int(r["time_ms"]) >= from_ms]
