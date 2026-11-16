# Security

## What Agentic-Datacenter is

Agentic-Datacenter is a simulation. It models industrial control systems; it is not one, and it must never be connected to real equipment.

- The simulator refuses to start if a protocol server would bind outside loopback or a container-internal network, unless that is explicitly overridden (`ADC-SAF-001`).
- No code path may open an industrial-protocol connection to an address outside the simulator's own networks (`ADC-SAF-002`).
- The adversarial scenarios use injected inputs and simulated misbehaviour inside the model. They contain no exploit code and target nothing outside the simulator.
- Keys and signed artifacts produced by a run are for the simulator only and are labelled non-production. Never supply a real operator key.

Agentic-Datacenter makes no claim of IEC 62443 certification, for itself or for anything evaluated with it.

At Stage 0 the repository contains design documents and an empty workspace. The two safety requirements above are implemented in Stage 1.

## Reporting a problem

Report privately to the repository owner through GitHub. Do not open a public issue for any of the following:

- A way to make the simulator bind to, or connect to, something outside its own networks.
- A way for a write to reach a controller model without a valid decision reference, or for any network path to reach a tier `T0` point.
- Restricted material in the repository or its history: text from the reference specification or from a standard, or the names covered by `ADC-PRV-002`.
- A secret or a real key committed by mistake.

Say what you observed, the commit, and how to reproduce it.

A weakness in a governance gate that Agentic-Datacenter merely exposes belongs with that gate's maintainers. For REMORA, report it to the REMORA project rather than here.

## Scope

The threat model, for the simulated facility and for the simulator as software, is in `docs/design/threat_model.md`.
