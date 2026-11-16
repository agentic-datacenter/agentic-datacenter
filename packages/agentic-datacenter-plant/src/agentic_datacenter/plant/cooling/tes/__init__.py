"""Thermal energy storage (`cooling.tes`).

The chilled water storage tank that covers the gap while chillers restart.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.cooling.tes.stub import Stub
from agentic_datacenter.plant.cooling.tes.unit import Tes

MODULE = ModuleEntry.from_package(__file__, factory=Tes, stub=Stub)
