"""Physical security signals (`security`).

Access control, interlocked portals, perimeter intrusion detection and gates, as a
source of events.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.security.stub import Stub
from agentic_datacenter.plant.security.unit import Security

MODULE = ModuleEntry.from_package(__file__, factory=Security, stub=Stub)
