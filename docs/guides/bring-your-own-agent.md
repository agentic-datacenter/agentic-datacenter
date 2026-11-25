# Bring your own agent: roadmap

External agent adapters are planned. Runs today use scripted agents. You can inspect a real simulator result and help shape what your agent will be able to read and propose.

- **See the evidence today.** The [Demo report](../demo/result-report.md) shows how scripted proposals affect temperature, IT load and operator approvals under a safety control.
- **Help design the interface.** [Open an issue](https://github.com/darklordVirtual/agentic-datacenter/issues) to share what your agent needs to read, what it proposes and which scenario would be useful.
- **Testing a safety control?** Use the [governance quickstart](bring-your-own-gate.md#try-the-example) to try it with the scripted agents.

## What you get, once it is built

Your agent runs in the same simulated facility, scenarios and seeds as everyone else's, under each safety control. A result card shows what its decisions did to temperatures, IT load, energy and approvals. Every command a control stopped is replayed as if it had run, so a careful agent is told from a hostile one by what would have happened.

## What exists today

- **Scripted agents.** Two are used by the benchmark:
  - `scripted_benign`, a careful operator that optimises energy and keeps to the rules;
  - `scripted_adversarial`, a hostile one that tries what the threat model lists.

  `scenario run` also takes `scripted_drift` and `scripted_flood`. They are in `packages/agentic-datacenter-scenarios/src/agentic_datacenter/scenarios/agents.py`.
- **The tool surface an agent sees.** Section 9.3 of the [design document](../design/SDD-ADC-001.md) describes it. An agent reads points and proposes through intent contracts, and never writes to the plant itself.
- **A scripted run to try:**

  ```sh
  uv run agentic-datacenter scenario run OP-03 --gate static_allowlist --agent scripted_adversarial
  ```

  The command prints the scenario outcome and writes its evidence bundle to `build/evidence/`.

## What is planned

- **An agent served over HTTP**, after the pattern of the [gate binding](bring-your-own-gate.md): one request per decision point with what the agent may read, one answer with its proposals.
- **A conformance check** of an agent before it is benchmarked, as `gate check` does for a gate.
- **Results kept apart.** Results of language-model agents are reported apart from the scripted ones and never pooled with them (SDD 12.1).

This is the first feature after the adoption phase (`CONTRIBUTING.md`). Until it is built, this page gives no command for an agent of your own.

[Back to the README](https://github.com/darklordVirtual/agentic-datacenter#readme)
