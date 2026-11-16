"""Faults of the pump station.

``pump_fail`` takes ``pump`` (1 to 3): a drive fault. ``pump_restore`` clears it.
"""

from __future__ import annotations

FAULTS = ("pump_fail", "pump_restore")
