"""Stub of `security`: fixed, documented behaviour with the module's ports."""

from agentic_datacenter.core.module import Inputs, LatchedModule


class Stub(LatchedModule):
    """Physical security signals, fidelity F0.

    No ports and no events.
    """

    def step(self, inputs: Inputs) -> None:
        """Apply the fixed behaviour."""
        pass
