"""Electrical room cooling (`cooling.eroom`).

The chilled water air conditioners of one electrical POD, on return-air control.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.cooling.eroom.stub import Stub
from agentic_datacenter.plant.cooling.eroom.unit import Eroom

MODULE = ModuleEntry.from_package(__file__, factory=Eroom, stub=Stub)
