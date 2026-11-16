"""Fire and life safety (`life_safety`).

The hardwired layer: fire alarm panel, air-sampling detection per POD, cause and effect,
emergency power off and the fire pump.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.life_safety.stub import Stub
from agentic_datacenter.plant.life_safety.unit import LifeSafety

MODULE = ModuleEntry.from_package(__file__, factory=LifeSafety, stub=Stub)
