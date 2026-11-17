# ADR 0023: Bounded replay, tiers, and comparing different kinds of gates

- **Status:** Accepted.
- **Date:** 2026-11-16
- **SDD:** 12.1; requirements `ADC-BEN-008`, `ADC-BEN-009`, `ADC-GOV-008`

## Context

A development benchmark of one gate with three seeds ran for more than eight hours and had not finished. The simulation itself runs at about 500 times real time. The cost is the counterfactual replay: every proposal of a run is replayed from its decision to the end of the scenario, so a scenario of length *T* with *n* proposals costs about *n·T/2* of simulation. `OP-10` lasts a simulated week and its hostile agent proposes at almost every decision point, about 640 times. A gate whose state cannot be restored has each branch replayed from the start, *n·T*. No outside project would spend days on a first result.

A survey of governance projects that might connect found three things the interface did not yet meet:

- most decide with two or three verdicts, often in words of their own;
- many decide on the raw tool call, not an intent contract;
- several keep state: sessions, budgets, ledgers.

The card could not show what a binary gate did with a step that asks for a person.

## Decisions

1. **Bounded replay.** `judge_run` takes a horizon: a branch runs that long after its decision and is compared with the actual run at the same instant, from harm marks kept every minute of the actual run. A horizon that reaches the end judges exactly as before. It also takes a cap on the proposals judged per run. They are chosen by SHA-256 of scenario, seed and proposal id, so the choice is the same on every machine and no gate can steer it. Both bounds, and how many proposals were judged out of how many, are on the card (`ADC-BEN-008`).
   A scenario can lengthen the horizon and shrink the cap (`judge_horizon_s`, `judge_max`). `OP-10` does: whether a step saved energy shows only over a day of weather and load.
2. **Tiers.** `agentic-datacenter bench run --tier quick|standard|full` sets length, seeds and bounds (`docs/bench/TIERS.md`). `full` replays every proposal to the end. It is the reference that the bounds of the other tiers are checked against.
3. **Fairness counts on every card** (`ADC-BEN-009`, `docs/bench/FAIRNESS.md`). These show what a gate let through that the contract or the premises did not allow, whatever came of it:
   - the verdicts a gate used;
   - proposals executed with fewer approvers than their contract asks for;
   - proposals executed on a premise Agentic-Datacenter established as false;
   - decisions a served gate failed to give.

   Card schema version 3.
4. **The served interface meets more projects** (`ADC-GOV-008`):
   - Common verdict words are read as the verdict they mean, and the service's own word is kept.
   - Each request carries a tool-call view and a session that is new for every gate Agentic-Datacenter builds.
   - `ADC_GATE_STATEFUL=1` makes branches replay from the start.
   - `command_gate` runs a command per request over standard input and output, for gates that run as hooks.

## Consequences

- A bounded replay can miss harm that shows only after the horizon. The comparison of every run with the same seed without an agent (ADR 0021) still sees all harm of the whole run, and the release check still refuses a card with it. The horizon of the season tier was chosen from a comparison with `full` on the library, recorded in `docs/bench/TIERS.md`.
- A sampled run's counts of false blocks and harms avoided are counts over the judged proposals. The rates are estimates over them. The card says how many were judged.
- A gate that cannot be restored still costs most in long scenarios, because each branch starts from the beginning. Forking the process at each decision would remove that cost. It is not done here.
- Verdicts that carry conditions, change the action or defer it, identity and delegation scenarios, and receipt verification are not in this ADR. `docs/guides/which-way-in.md` says so for each kind of project.
