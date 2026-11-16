"""LV power train with automatic transfer (`electrical.power_train`).

One 400/230 V power train: unit substation, main switchboard with utility and
generator breakers, and the automatic transfer controller of SDD 7.2.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.electrical.power_train.stub import Stub
from agentic_datacenter.plant.electrical.power_train.unit import PowerTrain

MODULE = ModuleEntry.from_package(__file__, factory=PowerTrain, stub=Stub)
