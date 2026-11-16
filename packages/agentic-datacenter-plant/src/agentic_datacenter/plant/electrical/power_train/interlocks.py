"""Hardwired interlock of one main switchboard. Tier T0.

Invariant ``INV-ATO-1``: the utility breaker and the generator breaker of one
switchboard are never both closed. The interlock stands between every close
command and the breaker, whatever issued the command: the transfer controller,
a manual operation, a supervisory write or a fault. Nothing in this file can be
reached from a network path.
"""

from __future__ import annotations


def permit_close(*, other_closed: bool, other_closing: bool) -> bool:
    """Say whether a source breaker may close.

    Args:
        other_closed: The other source breaker is closed, by its own contacts
            and not by what a controller believes.
        other_closing: The other source breaker has a close operation under way.

    Returns:
        True only when the other breaker is open and staying open.
    """
    return not other_closed and not other_closing
