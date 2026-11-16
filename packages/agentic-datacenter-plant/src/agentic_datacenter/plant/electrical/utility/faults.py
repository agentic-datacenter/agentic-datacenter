"""Scenario inputs of one utility incomer.

``set`` takes ``voltage_pu`` and ``frequency_pu`` (either may be omitted): a sag,
a swell or a frequency excursion. ``loss`` removes the supply; ``restore``
returns it to nominal.
"""

from __future__ import annotations

INPUTS = ("set", "loss", "restore")
