"""IT load of one POD (`electrical.it_load`).

The IT equipment of one POD: power drawn from two feeds, the heat it releases, and
server fans that respond to inlet temperature.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.electrical.it_load.stub import Stub
from agentic_datacenter.plant.electrical.it_load.unit import ItLoad

MODULE = ModuleEntry.from_package(__file__, factory=ItLoad, stub=Stub)
