"""The same interface suite Agentic-Datacenter runs on its own gates (ADC-GOV-004)."""

from example_gate import ExampleGate

from agentic_datacenter.governance.conformance import check_gate


def test_example_gate_passes_the_gate_interface_suite() -> None:
    check_gate(ExampleGate)
