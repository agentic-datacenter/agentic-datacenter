"""The time REMORA's governed path reads when it is embedded in the simulator.

REMORA is told this module's name (``REMORA_TIME_SOURCE_MODULE``) and calls
:func:`utc_now` for every reading of "now" on the governed path: token and
approval expiry, limit windows, audit timestamps. The gate binding sets the
value from simulated time before each call it makes.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

#: The calendar instant of simulated time zero. The simulation has no date of its own.
EPOCH = datetime(2000, 1, 1, tzinfo=UTC)
_now = EPOCH


def utc_now() -> datetime:
    """Return simulated time as a calendar instant."""
    return _now


def set_ms(simulated_ms: int) -> None:
    """Set the time to *simulated_ms* after the epoch."""
    global _now  # noqa: PLW0603 - the one value REMORA reads through this module
    _now = EPOCH + timedelta(milliseconds=simulated_ms)
