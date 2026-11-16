"""Faults and local actions of one UPS.

``fault`` takes the inverter out, so the load goes to the static bypass. ``reset``
returns the UPS to normal operation. ``set_soc`` takes ``pct`` and stands for a
degraded or partly discharged battery.
"""

from __future__ import annotations

FAULTS = ("fault", "reset", "set_soc")
