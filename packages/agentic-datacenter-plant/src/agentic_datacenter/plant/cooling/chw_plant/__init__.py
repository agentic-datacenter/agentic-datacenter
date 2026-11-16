"""Chilled water plant (`cooling.chw_plant`).

The three air-cooled chillers and their plant controller: staging, rotation, restart
after a power interruption.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.cooling.chw_plant.stub import Stub
from agentic_datacenter.plant.cooling.chw_plant.unit import ChwPlant

MODULE = ModuleEntry.from_package(__file__, factory=ChwPlant, stub=Stub)
