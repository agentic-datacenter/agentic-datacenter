"""Utility incomer (`electrical.utility`).

One 36 kV utility incomer: the voltage and frequency the site is offered, driven by
the scenario.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.electrical.utility.stub import Stub
from agentic_datacenter.plant.electrical.utility.unit import Utility

MODULE = ModuleEntry.from_package(__file__, factory=Utility, stub=Stub)
