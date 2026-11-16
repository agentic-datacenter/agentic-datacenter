"""Generator set (`electrical.genset`).

One standby generator with its controller: start, ramp, ready-to-load handshake,
loading and cooldown.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.electrical.genset.stub import Stub
from agentic_datacenter.plant.electrical.genset.unit import Genset

MODULE = ModuleEntry.from_package(__file__, factory=Genset, stub=Stub)
