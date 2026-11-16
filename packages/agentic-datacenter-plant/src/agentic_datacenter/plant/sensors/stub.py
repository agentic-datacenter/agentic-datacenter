"""Stub of `sensors`: fixed, documented behaviour with the module's ports."""

from agentic_datacenter.core.module import Inputs, LatchedModule


class Stub(LatchedModule):
    """Sensor models, fidelity F0.

    No ports. Measured values equal true values.
    """

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        pass
