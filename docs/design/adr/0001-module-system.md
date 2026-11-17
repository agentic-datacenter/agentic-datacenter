# ADR 0001: Plant built from self-contained modules joined by typed ports

- **Status:** Accepted.
- **Date:** 2026-11-12
- **SDD:** 5.1, 5.3; requirements `ADC-MOD-001` to `-005`

## Context

The simulator models a whole facility: power, cooling, fuel, life safety, security and sensors. Written as one program, it would be too large to review and impossible to test in parts. The benchmark also needs any subsystem to be replaceable by a simpler stand-in, and results must state how faithful each part is.

## Decision

1. The plant is 16 modules, one directory each under `agentic_datacenter.plant`: six electrical, six cooling, and fuel, life safety, security and sensors.
2. A module is a vertical slice: model, local controller, hardwired logic, point definitions, faults, a stub and its own tests.
3. Modules exchange values only through typed ports owned by `agentic-datacenter-core`. No plant module imports another. The profile lists the modules and connects their ports.
4. Inside a module the controller sees only the module's declared I/O points, never model internals.
5. Every module has a `module.yaml` manifest: id, semantic version, fidelity level `F0` to `F3`, ports provided and required, zone, requirement IDs covered and the path of its module spec.
6. Every module ships a stub with the same ports and a fixed, documented behaviour.
7. `modules.lock.yaml` is generated from the manifests and committed; CI fails when it is stale.
8. Boundaries are import-linter contracts, so a violation fails the build.

## Consequences

- A module can be developed, tested and demonstrated alone, and a facility is whatever the profile wires together.
- Coupling that would be a function call in a monolith becomes a port. Adding a port type is a core change and needs its own ADR and a conservation test.
- Values cross module boundaries once per step, so tightly coupled physics (for example chiller and loop) must be stable under that one-step delay or live in one module.
- Each module adds a manifest, a spec and a stub to maintain. That cost is accepted for reviewability.

## State when this was decided

No module existed yet. The layer contracts were in place (ADR 0005). The contract that keeps plant modules independent of each other was left for the first modules, because import-linter cannot reference packages that do not exist.
