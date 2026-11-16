"""Faults and local actions of the 36 kV switchboard.

A node is ``incomer_1``, ``incomer_2`` or ``feeder[<train>]``.

- ``fault_current`` takes ``node`` and ``amps``: a fault current at that node,
  seen by its relay and by the incomer relays behind it, for as long as the node
  is energized or until ``clear_fault``.
- ``clear_fault`` takes ``node``.
- ``reset`` takes ``breaker`` (a node): the manual reset at the relay.
- ``manual_open`` and ``manual_close`` take ``breaker``: local operation at the
  switchboard. A tripped breaker cannot be closed before it is reset.
- ``remote_request`` takes ``relay`` (``IED-BUS``, ``IED-INC-1``, ``IED-FDR-A``
  ...), ``service`` (``control``, ``setting-group``, ``write`` or ``file``) and
  ``client``: a request that reached the relay over the network. The relay
  refuses it, publishes ``protection.refused`` and changes nothing: nothing in
  a relay can be operated or re-parameterized over the network (SDD 8.5).
"""

from __future__ import annotations

ACTIONS = ("fault_current", "clear_fault", "reset", "manual_open", "manual_close")
REMOTE_SERVICES = ("control", "setting-group", "write", "file")
