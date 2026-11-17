# Security

## What Agentic-Datacenter is

Agentic-Datacenter is a simulation. It models industrial control systems; it is not one, and it must never be connected to real equipment.

- The simulator refuses to start if a protocol server would bind outside loopback or a container-internal network, unless that is explicitly overridden (`ADC-SAF-001`).
- No code path may open an industrial-protocol connection to an address outside the simulator's own networks (`ADC-SAF-002`).
- The adversarial scenarios use injected inputs and simulated misbehaviour inside the model. They contain no exploit code and target nothing outside the simulator.
- Keys and signed artifacts produced by a run are for the simulator only and are labelled non-production. Never supply a real operator key.

Agentic-Datacenter makes no claim of IEC 62443 certification, for itself or for anything evaluated with it.

Both safety requirements are implemented in `agentic_datacenter.net.guard`, and tested:

- `ADC-SAF-001`: `packages/agentic-datacenter-net/tests/test_bind_guard.py` tests the guard itself. Each protocol server is tested to refuse a bind outside loopback: the Modbus, BACnet, SNMP and OPC UA servers in `tests/protocol/`, and the IEC 61850 server in `tests/conformance/test_iec61850_denied_services.py` and `packages/agentic-datacenter-iec61850/tests/test_library.py`.
- `ADC-SAF-002`: `packages/agentic-datacenter-net/tests/test_no_external_clients.py` tests that a connection outside loopback or a declared container network is refused, with no override, and that no package outside the network layer imports a socket or protocol library.

These tests show what the guard refuses. They are not a proof that no other code path exists.

## Reporting a problem

Report privately through GitHub private vulnerability reporting: on the repository's **Security** tab, choose "Report a vulnerability". Do not open a public issue for any of the following:

- A way to make the simulator bind to, or connect to, something outside its own networks.
- A way for a write to reach a controller model without a valid decision reference, or for any network path to reach a tier `T0` point.
- Restricted material in the repository or its history: text from the reference specification or from a standard, or the names covered by `ADC-PRV-002`.
- A secret or a real key committed by mistake.

Say what you observed, the commit, and how to reproduce it.

A weakness in a governance gate that Agentic-Datacenter merely exposes belongs with that gate's maintainers. For REMORA, report it to the REMORA project rather than here.

## Scope

The threat model, for the simulated facility and for the simulator as software, is in `docs/design/threat_model.md`.
