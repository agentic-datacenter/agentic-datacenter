"""Savings of a branch against the baseline (ADR 0019, decision 6).

Baseline minus candidate, in kWh and per cent of the baseline. Cost is the
facility saving times the price the request supplied, and nothing else: no
default price and no extrapolation beyond the run.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from agentic_datacenter.whatif.models import EnergyPrice

SYSTEMS = ("facility", "chiller", "pump", "fan", "ups_loss")


def compare(
    baseline: Mapping[str, Any], candidate: Mapping[str, Any], price: EnergyPrice | None
) -> dict[str, Any]:
    """Return what *candidate* saves against *baseline*, from their energy figures."""
    out: dict[str, Any] = {}
    for system in SYSTEMS:
        key = f"{system}_kwh"
        if key not in baseline or key not in candidate:
            continue
        base, cand = float(baseline[key]), float(candidate[key])
        out[f"{system}_kwh_saved"] = base - cand
        out[f"{system}_saved_pct"] = 100.0 * (base - cand) / base if base > 0.0 else None
    out["it_kwh_difference"] = float(candidate["it_kwh"]) - float(baseline["it_kwh"])
    out["pue_baseline"], out["pue_candidate"] = baseline["pue"], candidate["pue"]
    out["pue_change"] = float(candidate["pue"]) - float(baseline["pue"])
    saved = out["facility_kwh_saved"]
    out["price_per_kwh"] = price.per_kwh if price is not None else None
    out["currency"] = price.currency if price is not None else None
    out["cost_saved"] = saved * price.per_kwh if price is not None else None
    out["model_estimate"] = True
    return out
