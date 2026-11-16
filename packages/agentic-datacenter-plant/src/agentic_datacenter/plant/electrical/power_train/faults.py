"""Faults and local actions of one power train.

Each name is accepted by :meth:`PowerTrain.inject`. Faults stay until
``clear_faults``; trips stay until ``reset``, which stands for the manual reset
at the device.
"""

from __future__ import annotations

#: A breaker operation that has no effect.
STUCK = ("util_brk_fail_open", "util_brk_fail_close", "gen_brk_fail_open", "gen_brk_fail_close")
#: A breaker opened by a trip. Takes ``kind``: ``protective`` (ground fault or
#: instantaneous; locks out all transfers) or ``other``.
TRIPS = ("util_brk_trip", "gen_brk_trip")
#: Local actions at the device. ``set_mode`` takes ``mode``; the manual
#: operations take ``breaker`` (``util`` or ``gen``).
ACTIONS = ("reset", "clear_faults", "set_mode", "manual_close", "manual_open")
