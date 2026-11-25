# Which way in for your project

Choose a path by what your integration produces. A local command is the shortest path to a first result for a tool that can already return a decision.

## Try a local adapter

From the repository root after [setup](../index.md#try-it), run:

```sh
export ADC_GATE_COMMAND="python examples/command-gate/adapter.py"
export ADC_GATE_NAME=example_command
uv run agentic-datacenter gate check command_gate
uv run agentic-datacenter bench run --tier quick --scenario OP-03 \
    --gate command_gate --gate static_allowlist --out build/first-command
```

Open `build/first-command/report.html` for the comparison, `result_card.json` for the figures, and `decisions.jsonl` for the proposal, verdict and recorded reasons. The adapter runs locally with the Python standard library. The quick run is a development result. Use the [public-test instructions](../bench/PUBLIC_TEST.md) for a frozen benchmark.

Copy the [MIT starter](https://github.com/darklordVirtual/agentic-datacenter/blob/main/examples/command-gate/adapter.py) and replace `decide()` with your adapter. The command receives one `{"endpoint": "/evaluate", "request": {...}}` envelope on standard input and emits one answer on standard output. Keep diagnostics on standard error. Use exit 1 for an adapter error. Exit 2 with empty standard output is an intentional refusal under the current hook convention. `gate check` verifies the interface. Use the scenario run to check that the adapter actually exercises your intended policy.

## Choose by capability

| Your project | Connect it as | What Agentic-Datacenter measures | Not there yet |
| --- | --- | --- | --- |
| **Decides on actions**: allow or deny, perhaps escalate or abstain | an HTTP service (`http_gate`), a command run per request (`command_gate`), or a Python package. [Bring your own gate](bring-your-own-gate.md). | Harm let through, false blocks, approvals asked for, and everything in [the fairness rules](../bench/FAIRNESS.md). | |
| **Decides with only allow and deny** | the same; answer `ALLOW` or `DENY` | the same. Proposals whose contract asks for a person are counted separately, so a binary gate is not compared on what it cannot express. | |
| **Uses its own words** (`permit`, `block`, `ask`, `require_approval`, `skip`) | the same; answer with your words | the same. Your word is kept on each decision. The words Agentic-Datacenter understands are listed in [the wire format](../reference/gate-http-v1.schema.json) (`verdict_aliases`). | Map native words in your adapter using their meaning. Use a non-executing verdict when the native decision cannot be represented. |
| **Decides on the raw tool call**, not an intent contract | the same; read `tool_call` (`name`, `arguments`, `writes`) instead of `proposal` | the same. Results say which view a gate used. | Agentic-Datacenter's agent proposes through contracts. There is no MCP or HTTP proxy slot to sit in yet. |
| **Keeps state**: sessions, budgets, quotas, rate limits, ledgers | the same, with `ADC_GATE_STATEFUL=1`; key what you keep by `session` | the same, with the floods and the incremental drift of the adversarial scenarios. Agentic-Datacenter replays a stateful gate from the start of the run, so its state is right. | |
| **Produces a score or risk number** | a service of a few lines that turns your score into a verdict, at a threshold fixed before the run and never tuned on the scenarios | the same, for that threshold. Run more than one threshold to show the trade-off. | |
| **Observes or advises only** | `ADC_GATE_PROFILE=SHADOW` | What your gate would have allowed and blocked. Nothing it says is executed. | |
| **Allows with conditions, changes the action, or defers it** | answer `DENY` or `VERIFY` for now | as for a gate | Verdicts that carry caps, a changed action or a later retry. |
| **Checks who may act**, not only what is within limits | as a gate; read the premise `authority(<principal>, <contract>)`, or work it out from the mandate record sent with the proposal (`mandate`), and with `ADC_GATE_DERIVES_AUTHORITY=1` be sent the record alone | In the next benchmark version: three scenarios where a mandate ends, passes on or is narrower than the step (ADR 0028), how many steps were executed without a mandate, and how many your gate refused saying so (`reason_codes: ["authority"]`). If your gate states its own finding (`authority_holds`) or which kind of no mandate it was (`reason_details`), how often each is what the register holds, and whether your gate was told the answer or worked it out (ADR 0031). | A gate is not asked who may approve: an approval from someone who has lost access is refused before any gate sees it. |
| **Issues identity, delegation or trust** | not as a gate yet | | Scenarios with signed, delegated, expired and revoked credentials. The actor is a principal and a credential string today; a mandate is an entry in a register. |
| **Signs or independently verifies receipts** | Start with a local evidence export and a verifier. A decision-making adapter may also return an opaque `decision_id` for comparison with the decision record. | Correlation for records that carry that identifier. | A verifier interface and validated binding of an external receipt to the proposal and outcome. The outcome message carries the simulator's decision reference and session. |

## Preserve the policy's meaning

- **Time and state.** Drive policy clocks from `premises.time_ms`. If a library needs UTC, explicitly pick and record a fixed test epoch and add the simulated elapsed time. Use `session` to isolate state across runs and replays. Treat it as a namespace rather than an input to the policy.
- **Approval.** Send `required_approvers` explicitly for `VERIFY`. The contract expresses one or two people in `premises.approval`. The starter preserves that count.
- **Conditional actions.** A capped, narrowed, rewritten or redirected action has its own safety semantics. Until a constrained-action interface is defined, report `DENY` or `ABSTAIN` when the requested writes cannot be approved as given. Use `VERIFY` when approval of those exact writes is a supported policy outcome.
- **Physical context.** Read the simulator's evaluated predicates and the bounded writes, including their previous values. Those fields describe the proposal's simulated context. Additional temperature, load, interlock or permit signals would need an explicit sampled context with units, quality and simulated time.
- **Evidence.** Use `decision_id` as a correlation identifier. The simulator's decision record and evidence hashes establish what was recorded in the run. An external signed statement needs its own verification and binding to the relevant action and outcome.

## Integration sequence

A local command needs no service or public registration. Move to the HTTP binding when you need a long-lived service, or use `SHADOW` for read-only recommendations. A post-run verifier can prototype against the [recorded demo](../demo/demo.json). For a fresh evidence bundle, use `scenario run` and inspect the manifest, decisions and change log written to the selected output directory. `scenario verify` checks the bundle against its manifest. If your integration needs new context or identity material, describe the missing field or behavior in an issue. You can identify your system when you choose to participate.

## What all of them get

- Matched scenarios, agents, seeds and oracle. A deterministic adapter and fixed inputs make the comparison reproducible.
- A first result in minutes (`--tier quick`) and a full one in a few hours on one machine (`--tier standard`). See [tiers](../bench/TIERS.md).
- Their own figures beside the built-in gates', under [rules that keep different kinds of gates comparable](../bench/FAIRNESS.md).

## What the result establishes

Agentic-Datacenter measures the consequences of decisions on a simulated plant. Identity verification, receipt authenticity and authorization each require evidence appropriate to the system being evaluated. Keep those claims distinct from the simulator's measurements.
