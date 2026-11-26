# How the benchmark works

One page for anyone: an operator, a maintainer of a governance system, a reviewer. What is measured, how a step is judged, how to run it at any time, and what a season adds.

## The question

An AI agent proposes changes to a simulated data center: setpoints, pumps, chillers, generators. A safety control, the *gate*, decides on each proposal: allow, deny, ask a person, or abstain. The benchmark asks: **did the gate stop the steps that would have done harm, let through the ones that would have helped, and what did its decisions cost the plant?**

## What runs

| Part | What it is |
| --- | --- |
| **The plant** | A generic simulated facility: power, cooling, IT load, fuel, life safety. Deterministic: the same seed gives the same plant. Not calibrated against a real site. |
| **The scenarios** | Scripted days in the plant's life: a chiller trips in a heat wave, the network drops, a mandate ends while a step waits for approval, an alarm text tries to instruct the agent. Operational (`OP-`) and adversarial (`AD-`). |
| **The agents** | By default two scripted agents with predefined, simulated calls: a careful one, which proposes what a good operator would, and a hostile one, which tries what the threat model lists. A language model can be the agent instead, and is then reported apart ([Bring your agent](../guides/bring-your-own-agent.md)). |
| **The gate** | Yours, or a built-in one. It is asked about every proposal; only the simulator writes to the plant, and only what the gate allowed. |
| **The judge** | Every step is replayed both ways: as if it had been carried out and as if it had not. A step is harmful or useful by what the plant then does, not by what anyone says about it. Every run is also compared with the same scenario and seed with no agent at all. |

## What comes out

- **`summary.md`**: each gate's figures in plain words, beside the built-in gates: harmful steps let through, safe steps blocked, scenarios without harm, runs worse than no agent, people asked per 24 h, steps executed without the approval or the mandate they need.
- **`report.html`** and **`result_card.json`**: the same, drawn, and every figure and every run.
- **`decisions.jsonl`**: every decision with the gate's reasons.
- **An evidence bundle** per scenario run, with the **action trace**: each action from proposal to plant, who observed each link, and whether a receipt was given, a signature checked and the write observed.
- **`bench check`**: refuses a card in which a harmful step got through.

## Run it, any time

You need no season, no registration and no key.

```sh
uv sync
# A first result for a gate, in minutes, beside the built-in gates:
uv run agentic-datacenter bench run --tier quick --gate static_allowlist --gate null_gate --out build/mine
cat build/mine/summary.md
# Your own gate, as a command per decision (see Bring your own gate):
export ADC_GATE_COMMAND="python examples/command-gate/adapter.py"
uv run agentic-datacenter bench run --tier quick --gate command_gate --gate static_allowlist --out build/mine
uv run agentic-datacenter bench check build/mine/result_card.json --gate command_gate
```

| Tier | Takes | For |
| --- | --- | --- |
| `quick` | minutes | trying a gate; a development run |
| `standard` | hours on one machine | a result of your own, three seeds |
| `season` | longer; split it over machines | what a season reports, thirty seeds |

`standard` and `season` run on a frozen version; on a branch that has moved past it, add `--allow-unfrozen`, and the card is labelled a development run. A run on a frozen version's tag, with its seeds, is the benchmark; anyone who makes it again gets the same card, byte for byte. To keep testing as this project grows, copy [the workflow for maintainers](https://github.com/darklordVirtual/agentic-datacenter/blob/main/examples/ci/agentic-datacenter.yml) into your repository.

## What a season adds

A season is the public, comparable round. It adds what a run of your own cannot:

1. **A frozen version.** The plant, scenarios, contracts, judge and agents are hashed and tagged before the season. Every card says which version it is.
2. **Hidden scenarios.** Track D varies every scenario with parameters drawn from a public randomness beacon at the registration deadline, so nobody, the authors included, can tune for them.
3. **A preregistered analysis.** The question, hypotheses and figures are fixed in advance ([preregistration](PREREGISTRATION.md)); changes are dated entries made before any result.
4. **The table of enrolled systems.** A system is named only after its maintainers enrolled it and agreed ([participants](participants.md)); its figures then stand beside the built-in gates', and weaknesses a run found are sent to them first.

Registration is always open and takes three fields ([public test](PUBLIC_TEST.md)). Seasons follow one another, four weeks each.

## What it does not tell you

- Nothing about a real facility. The plant is generic and simulated.
- Not a certification and not compliance.
- No better than its scenarios. If a weakness of your system is not tested, say which scenario would show it, in an issue.

The owner of this project also owns REMORA, one of the gates it measures. Frozen versions, the beacon, the preregistration, marked built-in gates and byte-for-byte reproduction are there so that this does not matter ([For maintainers of governance systems](../guides/for-governance-maintainers.md)).
