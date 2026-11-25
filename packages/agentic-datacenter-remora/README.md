# agentic-datacenter-remora

Binding. The REMORA gate binding and nothing else. The only distribution that imports REMORA.

- Import path: `agentic_datacenter_remora`
- May depend on: `agentic-datacenter-governance`, `remora-assurance[security,sdk,api]`

### Reviewing decision grants

REMORA signs each decision grant with Ed25519 (format `v3`); HMAC grants are not accepted. The gate's evidence (`gate_evidence.json` in a bundle) holds the public key, `grant_verification_key_ed25519`, and for each proposal the grant REMORA consumed, `spent_grant`: when the write was applied, when the command service refused it after dispatch, and when it went unanswered. It is null when no grant was consumed. A live token and the private key are never in it. The key is derived from the contract library, like REMORA's other simulator-only keys (ADR 0016, decision 6): it signs nothing outside a simulation.

Inspect a grant's `format`, `kid` and `request_id`. A REMORA SDK with a grant verifier (`remora.sdk.evidence`, REMORA-research pull request 1246) can also check its signature against the public key; the pinned REMORA does not have that module yet, so the check is not made here. Use the proposal's effect and the measured plant state to see what the action changed.
