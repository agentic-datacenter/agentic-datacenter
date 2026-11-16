"""What REMORA's service calls back into: the tool, the limit observer, the evidence check.

REMORA is told this module's name in its configuration and imports it itself.
It holds no logic of its own: each function hands over to whatever the gate
binding has put in place for the call that is running, and refuses when
nothing is in place. One callable serves every contract, so one measured
digest covers them all.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

#: Tool names to register: the compiled contract ids. Set before REMORA's service is built.
TOOL_IDS: list[str] = []
#: Applies the contract instance that is being executed right now. Set for one call.
DISPATCH: Callable[[Mapping[str, Any]], dict[str, Any]] | None = None
#: Returns the present value of a point, by the resource name a limit is kept under.
OBSERVE: Callable[[str], float] | None = None
#: Returns what an independent read of the plant says about an unknown outcome.
EVIDENCE: Callable[[str], bool] | None = None
EVIDENCE_SOURCE = "agentic-datacenter-plant-read"


def apply_contract(arguments: Mapping[str, Any]) -> dict[str, Any]:
    """Run the contract instance REMORA has just released for execution."""
    if DISPATCH is None:
        raise RuntimeError("no contract instance is being executed")
    return DISPATCH(arguments)


def register_tools(register: Callable[..., None]) -> None:
    """Register the one callable under every compiled contract id."""
    for tool_id in TOOL_IDS:
        register(tool_id, apply_contract)


def observe_limit_value(tenant: str, quantity: str, resource: str) -> float:
    """Return the present value of the point a movement limit is charged against."""
    if OBSERVE is None:
        raise KeyError(f"no observation for {quantity!r} on {resource!r}")
    return OBSERVE(resource)


def check_limit_evidence(tenant: str, operation: Any, evidence_ref: str) -> dict[str, Any]:
    """Say what an independent read of the plant found for an unknown outcome."""
    if EVIDENCE is None:
        raise KeyError(f"no evidence under {evidence_ref!r}")
    return {"executed": EVIDENCE(evidence_ref), "source": EVIDENCE_SOURCE}
