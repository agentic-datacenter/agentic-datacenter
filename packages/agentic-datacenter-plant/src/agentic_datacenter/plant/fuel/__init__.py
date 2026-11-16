"""Fuel oil system (`fuel`).

Bulk storage, polishing, transfer pumps and one sub-base tank per generator with its
level controller.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.fuel.stub import Stub
from agentic_datacenter.plant.fuel.unit import Fuel

MODULE = ModuleEntry.from_package(__file__, factory=Fuel, stub=Stub)
