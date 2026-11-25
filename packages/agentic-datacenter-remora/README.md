# agentic-datacenter-remora

Binding. The REMORA gate binding and nothing else. The only distribution that imports REMORA.

- Import path: `agentic_datacenter_remora`
- May depend on: `agentic-datacenter-governance`, `remora-assurance[security,sdk,api]`

### Reviewing decision grants

A governed run exports the spent decision grant alongside the proposal after REMORA
reports execution. Inspect its `format`, `kid` and `request_id`. Proposals that
have not executed carry a null `spent_grant`. Live pending tokens and the
private signing key are excluded from the evidence. The benchmark uses a fresh
Ed25519 decision key per service process. The integrated simulator hosts both
decision and execution in that process.

With a REMORA SDK that includes `remora.sdk.evidence`, an independent reader
can check a spent grant with a public key obtained from the benchmark operator.

```python
from remora.sdk.evidence import verify_grant_signature

grant = proposal["spent_grant"]
assert grant["request_id"] == proposal["remora_proposal_id"]
assert verify_grant_signature(grant, public_key=trusted_run_public_key)
```

The exported `grant_verification_key_ed25519` permits a local consistency check.
For independent attribution, compare it with the key recorded separately for
the run. Use the proposal's effect and the measured plant state to review what
the action actually changed.
