# Which way in for your project

Find the row that describes what your project does. Each row says how to connect it, what Agentic-Datacenter measures for it today, and what is not there yet. Every way in takes one service, command or package of yours and no change to Agentic-Datacenter.

| Your project | Connect it as | What Agentic-Datacenter measures | Not there yet |
| --- | --- | --- | --- |
| **Decides on actions**: allow or deny, perhaps escalate or abstain | an HTTP service (`http_gate`), a command run per request (`command_gate`), or a Python package. [Bring your own gate](bring-your-own-gate.md). | Harm let through, false blocks, approvals asked for, and everything in [the fairness rules](../bench/FAIRNESS.md). | |
| **Decides with only allow and deny** | the same; answer `ALLOW` or `DENY` | the same. Proposals whose contract asks for a person are counted separately, so a binary gate is not compared on what it cannot express. | |
| **Uses its own words** (`permit`, `block`, `ask`, `require_approval`, `skip`) | the same; answer with your words | the same. Your word is kept on each decision. The words Agentic-Datacenter understands are listed in [the wire format](../reference/gate-http-v1.schema.json) (`verdict_aliases`). | A word Agentic-Datacenter has no verdict for. Answer the nearest one, and say so in your result. |
| **Decides on the raw tool call**, not an intent contract | the same; read `tool_call` (`name`, `arguments`, `writes`) instead of `proposal` | the same. Results say which view a gate used. | Agentic-Datacenter's agent proposes through contracts. There is no MCP or HTTP proxy slot to sit in yet. |
| **Keeps state**: sessions, budgets, quotas, rate limits, ledgers | the same, with `ADC_GATE_STATEFUL=1`; key what you keep by `session` | the same, with the floods and the incremental drift of the adversarial scenarios. Agentic-Datacenter replays a stateful gate from the start of the run, so its state is right. | |
| **Produces a score or risk number** | a service of a few lines that turns your score into a verdict, at a threshold fixed before the run and never tuned on the scenarios | the same, for that threshold. Run more than one threshold to show the trade-off. | |
| **Observes or advises only** | `ADC_GATE_PROFILE=SHADOW` | What your gate would have allowed and blocked. Nothing it says is executed. | |
| **Allows with conditions, changes the action, or defers it** | answer `DENY` or `VERIFY` for now | as for a gate | Verdicts that carry caps, a changed action or a later retry. |
| **Checks who may act**, not only what is within limits | as a gate; read the premise `authority(<principal>, <contract>)` | In the next benchmark version: three scenarios where a mandate ends, passes on or is narrower than the step (ADR 0028), and how many steps were executed without a mandate. | Whether the person who approves still has standing. |
| **Issues identity, delegation or trust** | not as a gate yet | | Scenarios with signed, delegated, expired and revoked credentials. The actor is a principal and a credential string today; a mandate is an entry in a register. |
| **Signs receipts or evidence** | return your receipt's id as `decision_id`; it is kept on each decision beside Agentic-Datacenter's own reference | Whether every decision on the card has a matching receipt, which you can check from the evidence bundle | Checking a receipt's signature, and binding it to the proposal and its outcome. |

A row marked as not there yet is open work. Say in an issue which row your project is in, and it is planned with you.

## What all of them get

- The same 23 scenarios, agents, seeds and oracle as every other gate, and a result card that anyone can reproduce byte for byte.
- A first result in minutes (`--tier quick`) and a full one in a few hours on one machine (`--tier standard`). See [tiers](../bench/TIERS.md).
- Their own figures beside the built-in gates', under [rules that keep different kinds of gates comparable](../bench/FAIRNESS.md).

## What Agentic-Datacenter is, and is not

Agentic-Datacenter measures what a gate's decisions do to a simulated plant. It does not issue identity, sign attestations or certify anything. A signed record proves who made a decision. Whether that decision was safe is a separate question, and the one Agentic-Datacenter answers.
