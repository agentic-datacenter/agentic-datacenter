"""Events of the physical security system.

``event`` takes ``kind`` (``granted``, ``denied``, ``forced``, ``held`` or
``intrusion``) and ``where`` (a door, portal or perimeter zone, free text).
``clear`` takes ``kind`` (``forced``, ``held`` or ``intrusion``): a guard has
dealt with it. Events are signals only; nothing models a person acting on
equipment.
"""

from __future__ import annotations

FAULTS = ("event", "clear")
KINDS = ("granted", "denied", "forced", "held", "intrusion")
LATCHED = {"forced": "alarm_door_forced", "held": "alarm_door_held", "intrusion": "alarm_intrusion"}
