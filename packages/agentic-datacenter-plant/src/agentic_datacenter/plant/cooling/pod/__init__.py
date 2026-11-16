"""POD cooling (`cooling.pod`).

The air side of one POD: server air handlers with chilled water coils, the supply air
loop, and the thermal response of the hall.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.cooling.pod.stub import Stub
from agentic_datacenter.plant.cooling.pod.unit import Pod

MODULE = ModuleEntry.from_package(__file__, factory=Pod, stub=Stub)
