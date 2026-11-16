"""Outdoor conditions (`cooling.weather`).

Dry-bulb temperature and humidity at the site.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.cooling.weather.stub import Stub
from agentic_datacenter.plant.cooling.weather.unit import Weather

MODULE = ModuleEntry.from_package(__file__, factory=Weather, stub=Stub)
