"""Faults and scenario inputs of the fuel oil system.

``transfer_pump_failure`` and ``transfer_pump_restore`` take ``train``.
``stuck_level_switch`` takes ``train`` and ``state``: ``wet`` (the controller
believes the tank is full and never refills it) or ``dry`` (it believes the
tank is low and keeps filling until the independent high-high switch trips the
pump: an overfill). ``level_switch_clear`` takes ``train``.
``interstitial_leak`` takes ``location`` (``BULK`` or ``SUB_BASE``) and stops
every pump; ``leak_clear`` releases it. ``set_level`` takes ``train`` and
``pct``; ``set_bulk`` takes ``pct``: levels at the start of a scenario.
"""

from __future__ import annotations

FAULTS = (
    "transfer_pump_failure", "transfer_pump_restore", "stuck_level_switch",
    "level_switch_clear", "interstitial_leak", "leak_clear",
)  # fmt: skip
INPUTS = ("set_level", "set_bulk")
