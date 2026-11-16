"""Uninterruptible power supply (`electrical.ups`).

One online UPS with its battery: carries the IT load across a transfer and reports its
losses as heat to the electrical room.
"""

from agentic_datacenter.core.module import ModuleEntry
from agentic_datacenter.plant.electrical.ups.stub import Stub
from agentic_datacenter.plant.electrical.ups.unit import Ups

MODULE = ModuleEntry.from_package(__file__, factory=Ups, stub=Stub)
