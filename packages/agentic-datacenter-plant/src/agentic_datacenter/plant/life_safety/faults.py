"""Events and faults of fire and life safety.

``smoke`` takes ``pod`` and ``level`` (``NORMAL``, ``ALERT``, ``ACTION``,
``FIRE_1`` or ``FIRE_2``): what the air-sampling detector of that POD reads.
``panel_reset`` releases every latched confirmed fire whose detector is back
below the fire thresholds. ``epo`` and ``epo_reset`` take ``pod``: someone
operates, or resets, the emergency power off station. ``panel_fault`` and
``panel_fault_clear`` take nothing. ``sprinkler_pressure_drop`` and
``sprinkler_pressure_restore`` take nothing. ``fire_pump_failure`` and
``fire_pump_restore`` take nothing.

All of these are things that happen at the equipment. None can be reached
from a network.
"""

from __future__ import annotations

FAULTS = (
    "smoke", "panel_reset", "epo", "epo_reset", "panel_fault", "panel_fault_clear",
    "sprinkler_pressure_drop", "sprinkler_pressure_restore", "fire_pump_failure",
    "fire_pump_restore",
)  # fmt: skip
LEVELS = ("NORMAL", "ALERT", "ACTION", "FIRE_1", "FIRE_2")
