"""Faults of one POD's cooling.

``valve_stuck`` holds the chilled water valve where it is; ``clear`` releases it.
``leak`` raises the leak alarm and ``leak_clear`` drops it; isolation is manual
and is not modelled. ``sensor_reset`` returns every excluded zone sensor to the mean,
as a technician would after replacing one. ``ahu_fail`` and ``ahu_restore`` take
``unit`` (1 to the number of air handlers).
"""

from __future__ import annotations

FAULTS = (
    "valve_stuck", "clear", "leak", "leak_clear", "sensor_reset", "ahu_fail", "ahu_restore",
)  # fmt: skip
