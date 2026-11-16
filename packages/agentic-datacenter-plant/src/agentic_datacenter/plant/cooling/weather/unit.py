"""Outdoor conditions at the site."""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from agentic_datacenter.core.io import IOBoard, load_points
from agentic_datacenter.core.module import Inputs, ModuleContext, SimModule, param_number
from agentic_datacenter.core.ports import Weather as WeatherValue
from agentic_datacenter.core.state import JsonValue

from .faults import INPUTS

if TYPE_CHECKING:
    from agentic_datacenter.data import MeasuredSeries

POINTS = load_points(Path(__file__).parent / "points.yaml")
DAY_S = 86_400.0
SOURCES = ("synthetic", "measured")


def _text(params: Mapping[str, JsonValue], name: str, owner: str) -> str:
    value = params.get(name)
    if not isinstance(value, str) or not value:
        raise ValueError(f"{owner}: source measured needs the parameter {name}")
    return value


def _load(manifest: str) -> MeasuredSeries:
    try:
        from agentic_datacenter.data import load_series
    except ImportError as exc:  # pragma: no cover - depends on the installation
        raise ValueError(
            "source measured needs the optional distribution agentic-datacenter-data "
            "(install agentic-datacenter-plant[measured])"
        ) from exc
    return load_series(Path(manifest))


class Weather(SimModule):
    """Weather at fidelity F1: a daily sine cycle, a constant override and a heat wave.

    With ``source: synthetic`` (the default) the dry bulb is
    ``mean + swing * sin(2 * pi * (hour - 9) / 24)``, lowest at 03:00 and highest
    at 15:00, with simulated time starting at midnight.

    With ``source: measured`` the dry bulb, and the humidity if the series has
    it, come from a measured series read by ``agentic_datacenter.data`` (ADR 0018). The
    parameter ``anchor_utc`` is the historical instant that simulated t=0 stands
    for; values between samples are interpolated linearly, and a time outside
    the series or inside a gap beyond the declared tolerance stops the run.
    Scenario inputs override the series as they override the sine cycle.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create the weather of the profile."""
        super().__init__(ctx, params)
        self.io = IOBoard(POINTS)
        self.mean_c = param_number(params, "dry_bulb_c", 20.0)
        self.swing_c = param_number(params, "daily_swing_c", 0.0)
        self.humidity = param_number(params, "rel_humidity_pct", 50.0)
        self.source = str(params.get("source", "synthetic"))
        if self.source not in SOURCES:
            raise ValueError(f"{ctx.name}: unknown weather source {self.source!r}")
        self.series: MeasuredSeries | None = None
        self.anchor_utc = ""
        self.anchor_ms = 0
        if self.source == "measured":
            manifest = _text(params, "manifest", ctx.name)
            self.anchor_utc = _text(params, "anchor_utc", ctx.name)
            from agentic_datacenter.data import parse_utc_ms

            self.anchor_ms = parse_utc_ms(self.anchor_utc)
            self.series = _load(manifest)
        self.mode = "profile"
        self.held_c = self.mean_c
        self.peak_c = self.mean_c
        self._update()

    def _update(self) -> None:
        wave = math.sin(2.0 * math.pi * (self.ctx.now_ms / 1000.0 / DAY_S - 9.0 / 24.0))
        if self.mode == "set":
            dry_bulb = self.held_c
        elif self.mode == "heat_wave":
            dry_bulb = self.peak_c - 0.5 * self.swing_c * (1.0 - wave)
        elif self.series is not None:
            dry_bulb = self._measured("dry_bulb")
        else:
            dry_bulb = self.mean_c + self.swing_c * wave
        humidity = self.humidity
        if (
            self.mode == "profile"
            and self.series is not None
            and "rel_humidity" in self.series.columns
        ):
            humidity = self._measured("rel_humidity")
        self.io["dry_bulb_c"], self.io["rel_humidity_pct"] = dry_bulb, humidity

    def _measured(self, column: str) -> float:
        assert self.series is not None
        return self.series.value_at(column, self.anchor_ms + self.ctx.now_ms)

    def step_slow(self, inputs: Inputs) -> None:
        """Move along the daily cycle."""
        self._update()

    def step(self, inputs: Inputs) -> None:
        """Nothing happens between the one-second steps."""

    def quiescent(self) -> bool:
        """The model advances in :meth:`step_slow` only."""
        return True

    def provenance(self) -> dict[str, object] | None:
        """Return where a measured series came from, or None for the synthetic weather."""
        if self.series is None:
            return None
        return {"anchor_utc": self.anchor_utc, **self.series.provenance()}

    def forward_outputs(self) -> Mapping[str, object]:
        """Return the outdoor conditions."""
        io = self.io
        return {"ambient": WeatherValue(io.number("dry_bulb_c"), io.number("rel_humidity_pct"))}

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply one of the scenario inputs listed in ``faults.py``."""
        if fault not in INPUTS:
            super().inject(fault, **params)
            return
        if fault == "set":
            self.mode = "set"
            self.held_c = float(params["dry_bulb_c"])  # type: ignore[arg-type]
            if "rel_humidity_pct" in params:
                self.humidity = float(params["rel_humidity_pct"])  # type: ignore[arg-type]
        elif fault == "heat_wave":
            self.mode, self.peak_c = "heat_wave", float(params["peak_c"])  # type: ignore[arg-type]
        else:
            self.mode = "profile"
        self._update()
        self.ctx.wake()

    def snapshot(self) -> JsonValue:
        """Return the complete state of the weather."""
        state: dict[str, JsonValue] = {
            "io": self.io.snapshot(),
            "mode": [self.mode, self.held_c, self.peak_c, self.humidity],
        }
        if self.series is not None:
            # The identity of the data is part of the state, so a run on another
            # file (or another anchor) cannot have the same state hashes.
            state["series"] = [self.series.manifest_sha256, self.anchor_utc]
        return state

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("weather snapshot must be a mapping")
        if self.series is not None:
            expected = [self.series.manifest_sha256, self.anchor_utc]
            if list(state.get("series") or []) != expected:  # type: ignore[arg-type]
                raise ValueError("weather snapshot was taken on another series or anchor")
        self.io.restore(state["io"])
        mode = state["mode"]
        assert isinstance(mode, list | tuple)
        self.mode = str(mode[0])
        self.held_c, self.peak_c, self.humidity = (float(str(v)) for v in mode[1:])
