"""Engine, governor and voltage regulator of one generator set."""

from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class Rating:
    """What the profile says about one set.

    The transient limits are those of ISO 8528-5 performance class G3 as
    tabulated in secondary sources (SDD 6.6). They are reached at a load step
    of ``class_step`` of the rating; a larger step gives a proportionally
    larger excursion, which is outside the class.
    """

    rated_kw: float
    fuel_l_per_h_full: float
    fuel_l_per_h_quarter: float
    class_step: float = 0.6
    frequency_dip: float = 0.07
    frequency_rise: float = 0.10
    frequency_recovery_s: float = 3.0
    voltage_dip: float = 0.15
    voltage_rise: float = 0.20
    voltage_recovery_s: float = 4.0


class Engine:
    """Deviation of frequency and voltage from nominal after load steps."""

    def __init__(self, rating: Rating) -> None:
        """Create an engine at nominal speed and voltage with no load."""
        self.rating = rating
        self.load_kw = 0.0
        self.frequency_dev = 0.0
        self.voltage_dev = 0.0

    def apply_load(self, load_kw: float, dt_s: float) -> None:
        """Let earlier deviations decay, then add the deviation of this load step."""
        r = self.rating
        # Three time constants bring a deviation to 5 % of its peak by the recovery time.
        self.frequency_dev *= math.exp(-3.0 * dt_s / r.frequency_recovery_s)
        self.voltage_dev *= math.exp(-3.0 * dt_s / r.voltage_recovery_s)
        if abs(self.frequency_dev) < 1e-9:
            self.frequency_dev = 0.0
        if abs(self.voltage_dev) < 1e-9:
            self.voltage_dev = 0.0
        step = (load_kw - self.load_kw) / r.rated_kw / r.class_step
        if step > 0.0:
            self.frequency_dev -= r.frequency_dip * step
            self.voltage_dev -= r.voltage_dip * step
        elif step < 0.0:
            self.frequency_dev += r.frequency_rise * -step
            self.voltage_dev += r.voltage_rise * -step
        self.load_kw = load_kw

    def settled(self) -> bool:
        """No transient is in progress."""
        return self.frequency_dev == 0.0 and self.voltage_dev == 0.0

    def fuel_l_per_h(self) -> float:
        """Return the fuel burn: linear in load from 25 % to 100 %, floored below that."""
        r = self.rating
        slope = (r.fuel_l_per_h_full - r.fuel_l_per_h_quarter) / 0.75
        burn = r.fuel_l_per_h_quarter + slope * (self.load_kw / r.rated_kw - 0.25)
        return max(burn, 0.5 * r.fuel_l_per_h_quarter)
