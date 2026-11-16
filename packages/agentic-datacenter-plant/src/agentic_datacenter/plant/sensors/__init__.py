"""Sensor models (`sensors`).

The model every measured point passes through: accuracy, resolution and failure modes.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.sensors.stub import Stub
from agentic_datacenter.plant.sensors.unit import Sensors

MODULE = ModuleEntry.from_package(__file__, factory=Sensors, stub=Stub)
