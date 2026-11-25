# Bring your agent

External agent adapters are planned. Current runs use scripted agents that propose actions to the same simulated plant.

Start with the [OP-03 scenario](../../packages/agentic-datacenter-scenarios/src/agentic_datacenter/scenarios/library/OP-03.yaml), a chiller trip during a heat wave. The [demo report](../demo/result-report.md) shows what happens to temperatures, IT load and operator approvals when agent proposals are evaluated with different safety controls.

If your system decides whether a proposed action should run, it can connect today as a [governance gate](bring-your-own-gate.md). See [available integration paths](which-way-in.md) for the supported inputs and limits.

To help shape the agent interface, [open an issue](https://github.com/darklordVirtual/agentic-datacenter/issues/new) about the observations your agent needs and the actions it proposes.
