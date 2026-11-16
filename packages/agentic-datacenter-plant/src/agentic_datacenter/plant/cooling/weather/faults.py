"""Scenario inputs of the weather.

``set`` takes ``dry_bulb_c`` and optionally ``rel_humidity_pct`` and holds them
constant. ``heat_wave`` takes ``peak_c``: the daily cycle then peaks there and the
nights stay within one daily swing of it. ``clear`` returns to the profile.
"""

from __future__ import annotations

INPUTS = ("set", "heat_wave", "clear")
