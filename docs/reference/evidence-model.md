# Evidence model

Every run of Agentic-Datacenter leaves the same chain of records, from the scenario to what happened in the plant. A reader can follow one proposal from the moment the agent saw something to the consequence, and check every link without the simulator. This page names the links and where each is kept. It describes evidence bundle schema 1 and result card schema 6.

## The chain

| # | Link | What it answers | Where it is kept |
| --- | --- | --- | --- |
| 1 | Scenario | What was set up: faults, notes, attempts, their times, and what the run must achieve | `manifest.json`: `scenario`, `scenario_hash`; the scenario file itself |
| 2 | Facility and rules | Which plant and which contracts the run used | `manifest.json`: `profile_hash`, `contracts_hash`, `lowest_fidelity` |
| 3 | Observation | What the plant was doing, minute by minute | `state_hashes.jsonl`: the hash of the whole simulated state each minute |
| 4 | Proposal | What the agent asked for, with which arguments and why, under which identity, and what it claimed about itself | `decisions.jsonl`: `proposal_id`, `contract_id`, `arguments`, `rationale`, `credential`, `principal`, `claimed_actor` |
| 5 | Premises | What the contract required of the plant at that instant, and whether it held | `decisions.jsonl`: `premises`, `contract_errors`, `limit_errors` |
| 6 | Gate decision | The verdict, the reasons, and how many people the gate asked for | `decisions.jsonl`: `gate`, `profile`, `verdict`, `reasons`, `reason_codes`, `required_approvers`, `decision_ref` |
| 7 | Approval | Who approved or refused, and any approval refused because the person had lost standing | `decisions.jsonl`: `approvers`, `approval_refusals`; `escalations.jsonl` |
| 8 | Action | What was written to the plant, by whom, under which decision, and whether the command service accepted it | `change_log.jsonl`: `tag`, `old`, `new`, `actor`, `decision_ref`, `accepted`, `code` |
| 9 | Outcome | What became of the decision: executed, refused by a person, not executed, rolled back | `decisions.jsonl`: `outcome`, `outcome_detail` |
| 10 | Consequence | What the run did to the facility, against the scenario's criteria | `metrics.json`: `metrics`, `passed`, `failed_criteria` |
| 11 | Counterfactual | For each refused proposal, what would have happened had it run: harm avoided, or a useful step lost | the result card: `harm_avoided`, `false_blocks`, `required_blocks`, `approvals_declined` |
| 12 | Comparison | Whether the run with the agent ended worse than the same run with no agent | the result card: `vs_no_agent` per run, `runs_worse_than_no_agent` per gate |
| 13 | Action trace | One action from proposal to plant, who observed each link, and whether a receipt was given, a signature checked and the write observed | `action_trace.jsonl` and `action_trace.md` (ADR 0038) |
| 14 | What ran | The agent and the gate, each verified here, built in, or only reported | `manifest.json`: `identity` |
| 15 | Finding | A claim several runs support, with its evidence, conditions, limits and replications, kept beyond one run | `findings/ADC-FIND-<nnnn>.yaml` and [the findings page](findings.md) |

Three things are kept apart on purpose, because they are different claims.

- **Proposed:** the agent asked for something harmful (links 4 and 11).
- **Refused:** the gate stopped it (link 6).
- **Executed:** it reached the plant (link 8).

A gate is judged on the third. An agent that proposes harm is the scenario working, not a failure of the gate.

## How the chain is held together

- `decision_ref` joins a decision (link 6) to every write it allowed (link 8). A write with no valid decision behind it breaches `INV-GOV-2`, and the release check refuses the card ([Invariants](invariants.md)).
- `manifest.json` carries the SHA-256 of every other file in the bundle, the code commit and the gate's commit. `agentic-datacenter scenario verify <bundle>` checks them.
- The same scenario, seed, profile, contracts and code give the same bytes. A bundle made on a second machine can be compared file by file.
- A gate may add its own record, `gate_evidence.json`. `remora_governed` puts its audit chain there.

## What the chain does not show

- It shows what happened in the simulated facility, not what would happen at a real one. Every bundle says so in `statements`, and names the lowest fidelity of the modules it used.
- It does not show why a gate decided as it did, beyond the reasons the gate gives.
- It holds no personal data. Identities are those of the simulated principals.

## For gate developers

A served gate gets links 4 and 5 in its request, the proposal with the identity behind it and the premises at that instant ([schema](gate-http-v1.schema.json)), and answers link 6. It never sees links 8 to 12 before it answers. That is what makes a counterfactual judgement fair.
