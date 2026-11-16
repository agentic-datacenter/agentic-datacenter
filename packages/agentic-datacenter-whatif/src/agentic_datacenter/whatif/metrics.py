"""What a branch did to the plant, measured from its true state (ADR 0019, decisions 6 and 7).

Energy by system is integrated at the harness's ten-second sample, the same
way the harness integrates facility energy, and kept as fifteen-minute series.
Violations are split into two kinds with no field in common: physical (what
happened to the plant) and governance (what happened on the control path).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.scenarios.harness import SAMPLE_S, Metrics, ScenarioRun

INTERVAL_S = 900
#: Physical violations and margins, in the order they are shown.
PHYSICAL = (
    "critical_pod_minutes",
    "excursion_pod_minutes",
    "it_kwh_lost",
    "interlock_steps",
    "min_tes_charge_pct",
    "max_pod_c",
)
#: Governance violations: writes the control path should never have let through.
GOVERNANCE = (
    "executed_over_limit",
    "executed_on_stale_premises",
    "replays_accepted",
    "writes_outside_contract",
)
_SYSTEMS = ("chiller", "pump", "fan", "ups_loss", "facility", "it")


def physical_violations(
    metrics: Metrics, *, min_tes_charge_pct: float, max_pod_c: float
) -> dict[str, float]:
    """Return the physical violations and margins of a run."""
    return {
        "critical_pod_minutes": metrics.critical_pod_minutes,
        "excursion_pod_minutes": metrics.excursion_pod_minutes,
        "it_kwh_lost": metrics.it_kwh_lost,
        # Steps on which a train had its utility and generator breakers closed together.
        "interlock_steps": float(metrics.breakers_both_closed_steps),
        "min_tes_charge_pct": min_tes_charge_pct,
        "max_pod_c": max_pod_c,
    }


def governance_violations(metrics: Metrics) -> dict[str, int]:
    """Return the governance violations of a run."""
    return {name: int(getattr(metrics, name)) for name in GOVERNANCE}


@dataclass
class Meter:
    """Observes a run after every sample: energy by system, margins, fifteen-minute series."""

    kwh: dict[str, float] = field(default_factory=lambda: dict.fromkeys(_SYSTEMS, 0.0))
    min_tes_charge_pct: float = 100.0
    max_pod_c: float = float("-inf")
    series: list[dict[str, JsonValue]] = field(default_factory=list)
    _interval: dict[str, float] = field(default_factory=lambda: dict.fromkeys(_SYSTEMS, 0.0))
    _hottest: float = float("-inf")
    _lowest_charge: float = float("inf")

    def __call__(self, run: ScenarioRun) -> None:
        """Add one sample of true plant state."""
        hours = SAMPLE_S / 3600.0
        kw = dict.fromkeys(_SYSTEMS, 0.0)
        hottest, charge, setpoint = float("-inf"), float("inf"), float("nan")
        for _, manifest, module in run.world.plant.instances():
            io = getattr(module, "io", None)
            kind = manifest.id
            if kind == "cooling.chw_plant":
                kw["chiller"] += float(io["power_kw"])  # type: ignore[index]
                setpoint = float(io["chws_sp_c"])  # type: ignore[index]
            elif kind == "cooling.pump_station":
                kw["pump"] += float(io["power_kw"])  # type: ignore[index]
            elif kind in ("cooling.pod", "cooling.eroom"):
                kw["fan"] += float(io["fan_kw"])  # type: ignore[index]
                if kind == "cooling.pod":
                    hottest = max(hottest, float(module.ts))  # type: ignore[attr-defined]
            elif kind == "electrical.ups":
                kw["ups_loss"] += float(io["loss_kw"])  # type: ignore[index]
            elif kind == "cooling.tes":
                charge = min(charge, float(io["charge_pct"]))  # type: ignore[index]
            elif kind == "electrical.mv_switchgear":
                kw["facility"] += float(module.power_balance()["in_kw"])  # type: ignore[attr-defined]
            elif kind == "electrical.it_load":
                kw["it"] += float(io["served_kw"])  # type: ignore[index]
        for system in _SYSTEMS:
            self.kwh[system] += kw[system] * hours
            self._interval[system] += kw[system] * hours
        self.max_pod_c = max(self.max_pod_c, hottest)
        self.min_tes_charge_pct = min(self.min_tes_charge_pct, charge)
        self._hottest = max(self._hottest, hottest)
        self._lowest_charge = min(self._lowest_charge, charge)
        if run.second % INTERVAL_S == 0:
            per_h = 3600.0 / INTERVAL_S
            self.series.append({
                "t_s": run.second,
                "facility_kw": self._interval["facility"] * per_h,
                "it_kw": self._interval["it"] * per_h,
                "chiller_kw": self._interval["chiller"] * per_h,
                "pump_kw": self._interval["pump"] * per_h,
                "fan_kw": self._interval["fan"] * per_h,
                "hottest_pod_c": self._hottest,
                "chws_sp_c": setpoint,
                "tes_charge_pct": self._lowest_charge,
            })  # fmt: skip
            self._interval = dict.fromkeys(_SYSTEMS, 0.0)
            self._hottest, self._lowest_charge = float("-inf"), float("inf")

    def energy(self, metrics: Metrics) -> dict[str, JsonValue]:
        """Return the energy figures of the run: the harness's own facility and IT energy."""
        return {
            "facility_kwh": metrics.facility_kwh,
            "it_kwh": metrics.it_kwh,
            "pue": metrics.pue,
            "chiller_kwh": self.kwh["chiller"],
            "pump_kwh": self.kwh["pump"],
            "fan_kwh": self.kwh["fan"],
            "ups_loss_kwh": self.kwh["ups_loss"],
            "model_estimate": True,
        }
