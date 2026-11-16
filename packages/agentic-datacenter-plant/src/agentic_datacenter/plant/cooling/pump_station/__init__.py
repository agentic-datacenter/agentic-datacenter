"""Chilled water pump station (`cooling.pump_station`).

The packaged pump station: three variable-speed pumps, two duty and one standby.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.cooling.pump_station.stub import Stub
from agentic_datacenter.plant.cooling.pump_station.unit import PumpStation

MODULE = ModuleEntry.from_package(__file__, factory=PumpStation, stub=Stub)
