"""36 kV switchboard (`electrical.mv_switchgear`).

The metal-clad 36 kV switchboard: two incomers, one feeder per unit substation, and the
six protection relays that later speak IEC 61850.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.electrical.mv_switchgear.stub import Stub
from agentic_datacenter.plant.electrical.mv_switchgear.unit import MvSwitchgear

MODULE = ModuleEntry.from_package(__file__, factory=MvSwitchgear, stub=Stub)
