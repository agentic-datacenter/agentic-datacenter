"""Decision references: how a decision is tied to exactly the writes it authorizes."""

from __future__ import annotations

import hashlib

from agentic_datacenter.core.state import JsonValue, canonical_bytes

#: How long an authorization stays valid, in simulated milliseconds.
DECISION_TTL_MS = 30_000


def decision_ref(
    gate: str,
    proposal_id: str,
    contract_id: str,
    verdict: str,
    writes: JsonValue,
    reasons: JsonValue,
    time_ms: int,
) -> str:
    """Return the reference of a decision: the hash of everything it decided.

    Two decisions with the same content at the same gate time have the same
    reference, so a run is reproducible; any change to the writes changes it.
    """
    body: JsonValue = {
        "gate": gate, "proposal": proposal_id, "contract": contract_id, "verdict": verdict,
        "writes": writes, "reasons": reasons, "time_ms": time_ms,
    }  # fmt: skip
    return "dec-" + hashlib.sha256(canonical_bytes(body)).hexdigest()[:32]


def write_ref(reference: str, index: int) -> str:
    """Return the single-use reference of the *index*-th write of a decision."""
    return f"{reference}#{index}"
