# agentic-datacenter-whatif

What-if for one proposed change: what does it save in simulation, which physical margins does it use up, and can the agent carry it out under its contract and the gate. The change is played as three branches from one start state (baseline, a hypothetical physical branch held by a simulator-internal override, and a governed branch with a goal-seeking agent under `GOVERNED`), with a contract preflight and REMORA's policy analysis beside the physics.

- Import path: `agentic_datacenter.whatif`
- May depend on: `core`, `supervisory`, `governance`, `scenarios`; REMORA only through `agentic_datacenter_remora`, from `agentic_datacenter.whatif.policy`, and the package works without it
- Decision: `docs/design/adr/0019-what-if.md`; design document section 10.4
- Commands: `agentic-datacenter whatif run --spec <json> --out <dir>`, `agentic-datacenter whatif policy --spec <json> --out <dir>`, `agentic-datacenter whatif verify <dir>`
- Job API: `agentic_datacenter.whatif.api.create_router`

All results are simulation results. Energy figures come from models at fidelity F1 and are model estimates.
