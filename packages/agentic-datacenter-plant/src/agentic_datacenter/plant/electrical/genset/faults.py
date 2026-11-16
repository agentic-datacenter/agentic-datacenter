"""Faults and local actions of one generator.

``start_failure`` makes the next start attempt end in a fault. ``trip`` faults a
running or stopped set at once. ``reset`` is the manual reset at the set.
"""

from __future__ import annotations

FAULTS = ("start_failure", "trip", "reset")
