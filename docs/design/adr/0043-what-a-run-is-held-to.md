# ADR 0043: What a run is held to: the control, the agent, and what had not happened yet

- **Status:** Accepted on 2026-11-27, for `benchmark-v1.6`. The owner asked for it after the first quick run of a whole system through every scenario.
- **Date:** 2026-11-27
- **SDD:** 10, 12.1; ADR 0023, 0030

## Context

A run passed when every criterion of its scenario was met. Two kinds of criterion are not the control's to meet.

- **The agent's own conduct.** `OP-06` asks that a person is told about a leak. Only the agent can tell a person. The hostile agent never does, and under every control, the strictest and none at all, the run was "not passed".
- **What had not happened yet.** `OP-07` lasts 31 hours, and its fuel runs low after many of them. A quick run plays two. The criterion that a person is told was "failed" in a run that ended before there was anything to tell.

The first quick run of a system through all 38 scenarios read "73 of 76 passed". The three were these, and they were the same three under the limits-only control and under no control. The release check already wrote them down as notes. The run's own verdict, the card's count of runs passed, and the line a first-time user reads after `scenario run` did not.

## Decision

A criterion that was not met is one of three things, and a run says which.

1. **Not reached.** A criterion that asks for something to happen (`min`), in a run that ended before the scenario's last event. What had not happened yet proves nothing. A criterion that forbids something (`max`) is held to in every run, however short.
2. **The agent's own conduct.** A criterion on a metric that only the agent can move, in a run that reached the scenario's last event. Today that is `escalations`. It is what an agent is judged by, and no control fails for it.
3. **Failed.** Everything else. Only this makes a run not pass.

`RunResult` and each run of a card carry `agent_conduct` and `not_reached` beside `failed_criteria`, only where there is any. `scenario run` prints each on a line of its own. The release check reads them as the notes they were.

## Consequences

- A control is judged by what a control can do. The count of runs passed means that for every gate.
- An agent is judged by its conduct, which is on the card for whoever compares agents.
- A run of a scenario with no such criterion is the run it was. The judge's hash changes, so this is `benchmark-v1.6`; every scenario, the contracts, the agents and the profile hash as before.
