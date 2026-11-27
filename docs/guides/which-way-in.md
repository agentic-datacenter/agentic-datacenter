# Which way in for your project

New here and not from the data center world? Start with [Your first half hour](first-half-hour.md). Otherwise, choose a path by what your integration produces. A local command is the shortest path to a first result for a tool that can already return a decision. What a maintainer gets, and what it costs, is on [For maintainers of governance systems](for-governance-maintainers.md).

## What does your project bring?

A project need not be a gate to take part. Start from what yours produces.

| Your project | Brings | The shortest way in | What you get back |
| --- | --- | --- | --- |
| Decides whether an action may run: a policy engine, a guard, an approval flow | **decisions** | [Try a local adapter](#try-a-local-adapter), below | What your decisions did to the plant: harm let through, sound steps blocked, people asked, beside two reference controls |
| Knows something about who is acting and decides nothing: identity, delegation, trust or risk signals | **findings** | The same adapter, with `ADC_GATE_PROFILE=SHADOW`. Answer with your finding, for example `"authority_holds": false`, and any verdict. Nothing you say is executed. | How often your finding was what the register holds, on mandates that were withdrawn, expired, passed on or forged ([Signed mandates](bring-your-own-gate.md#signed-mandates-in-two-terminals)) |
| Makes records of what happened: receipts, attestations, signed logs | **evidence** | Give a receipt with each answer, or export them as JSON lines ([Integration sequence](#integration-sequence)) | Each receipt checked against what happened in the run, and its signature with your key or your own verifier |
| Checks records others made: a verifier, an auditor, an observer | **verification** | No adapter. Run any scenario, and read its evidence bundle: `manifest.json`, `decisions.jsonl`, `action_trace.jsonl` and `execution.json` ([Evidence model](../reference/evidence-model.md)) | A bundle with known contents to run your verifier against, the same bytes for everyone who makes it |

One project may bring several. Whichever it is, [enrolment](../bench/participants.md) asks the same of everyone: what you bring, what of the interface you use, and how you stand to this project.

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

Copy the [MIT starter](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/examples/command-gate/adapter.py) and replace `decide()` with your adapter. The command receives one `{"endpoint": "/evaluate", "request": {...}}` envelope on standard input and emits one answer on standard output. Keep diagnostics on standard error. Use exit 1 for an adapter error. Exit 2 with empty standard output is an intentional refusal under the current hook convention. `gate check` verifies the interface. Use the scenario run to check that the adapter actually exercises your intended policy.

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
| **Allows with conditions, changes the action, or defers it** | answer `DENY` or `VERIFY` for now | as for a gate | Verdicts that carry caps, a changed action or a later retry, judged on the action as carried out: proposed for the next benchmark version (ADR 0037). |
| **Checks who may act**, not only what is within limits | as a gate; read the premise `authority(<principal>, <contract>)`, or work it out from the mandate record sent with the proposal (`mandate`), and with `ADC_GATE_DERIVES_AUTHORITY=1` be sent the record alone | Scenarios where a mandate ends, passes on or is narrower than the step (ADR 0028), how many steps were executed without a mandate, and how many your gate refused saying so (`reason_codes: ["authority"]`). If your gate states its own finding (`authority_holds`) or which kind of no mandate it was (`reason_details`), how often each is what the register holds, and whether your gate was told the answer or worked it out (ADR 0031). | A gate is not asked who may approve: an approval from someone who has lost access is refused before any gate sees it. |
| **Issues or verifies identity, delegation or trust** | as a gate, with `ADC_GATE_VERIFIES_MANDATES=1`: be sent the mandate as signed statements and the issuers the site trusts, and neither the premise nor the register's record | Whether your gate takes a forged statement, misses a withdrawal or an expiry, lets a principal act on more than was passed on to it or after its source was withdrawn, takes a signature made with a retired key, or stops a sound step (`AD-16` to `AD-19`, `OP-15`, `OP-16`, ADR 0039, ADR 0040). The rule, test vectors and a reference to port are in [Signed mandate statements](../reference/mandate-statements.md). | The keys are test keys, the same in every run. A statement dated back by whoever holds a retired key is not modelled. |
| **Signs or independently verifies receipts** | any of the three; answer with your `decision_id` and, if you like, your `receipt` object, and export your receipts as JSON lines keyed by the request's `correlation.correlation_id` | `agentic-datacenter gate verify-receipts` checks, locally, that each receipt names the right action (`action_ref`), the verdict you answered and the outcome, and, for an evidence bundle, that the bundle is what its manifest says (ADR 0036) | Give your public key (`ADC_GATE_RECEIPT_KEY`, or `--key`) and the Ed25519 signature of each receipt is checked too, over the receipt without its signature as canonical JSON (ADR 0041). Other signature schemes stay with your own verifier. |

## Preserve the policy's meaning

- **Time and state.** Drive policy clocks from `premises.time_ms`. A library that needs UTC gets it in `correlation.issued_at`: simulated time from a fixed anchor, `2026-01-01T00:00:00Z` unless `ADC_GATE_EPOCH` says another, never the wall clock. Use `session` to isolate state across runs and replays. Treat it as a namespace rather than an input to the policy.
- **Approval.** Send `required_approvers` explicitly for `VERIFY`. The contract expresses one or two people in `premises.approval`. The starter preserves that count.
- **Conditional actions.** A capped, narrowed, rewritten or redirected action has its own safety semantics. Until a constrained-action interface is defined, report `DENY` or `ABSTAIN` when the requested writes cannot be approved as given. Use `VERIFY` when approval of those exact writes is a supported policy outcome.
- **Physical context.** Read the simulator's evaluated predicates and the bounded writes, including their previous values. With `ADC_GATE_CONTEXT=1` each request also carries `context`: a read-only sample of temperatures, load, interlocks, margins and alarms, each point with value, unit, quality, simulated time and `observed_at`. Its `resolution_source` is `simulated_point_database`: what the simulator held, not attested by a sensor. Work permits are not modelled yet, and `permits` says so.
- **Evidence.** The request and its outcome message carry the same `correlation_id` and `action_ref`, the SHA-256 of the proposed action in canonical JSON. Bind your receipt to both. The decision record keeps them, with your `decision_id` and `receipt`, in `gate_detail`; `gate verify-receipts` compares your exported receipts with it. A signature in your receipt needs your own verifier.

## Integration sequence

A local command needs no service or public registration. Move to the HTTP binding when you need a long-lived service, or use `SHADOW` for read-only recommendations. A post-run verifier starts from a fresh evidence bundle: `scenario run` writes the manifest, decisions and change log, and `scenario verify` checks the bundle against its manifest. The starter shows the whole loop:

```sh
export ADC_GATE_COMMAND="python examples/command-gate/adapter.py" ADC_GATE_NAME=example_command
export ADC_GATE_CONTEXT=1 ADC_RECEIPTS_FILE=build/receipts.jsonl
rm -f build/receipts.jsonl    # the starter adds to the file; start each run with none
uv run agentic-datacenter scenario run OP-03 --gate command_gate --seconds 1800 --out build/receipts-run
uv run agentic-datacenter gate verify-receipts build/receipts-run build/receipts.jsonl --require-all
```

To have the signatures of your receipts checked too, sign them and give the public key. The starter signs with an Ed25519 key made from a seed of your own, 64 hexadecimal digits:

```sh
export ADC_RECEIPTS_KEY_SEED=$(python -c "import secrets; print(secrets.token_hex(32))")
export ADC_RECEIPTS_FILE=build/receipts-signed.jsonl
PUB=$(uv run python examples/command-gate/adapter.py --public-key)
rm -f build/receipts-signed.jsonl
uv run agentic-datacenter scenario run OP-03 --gate command_gate --seconds 1800 --out build/receipts-signed-run
uv run agentic-datacenter gate verify-receipts build/receipts-signed-run build/receipts-signed.jsonl \
    --require-all --require-signed --key "$PUB"
```

It ends with `signatures: 5 verified, 0 failed, 0 not signed`. Change one line of the file and it fails. With `ADC_GATE_RECEIPT_KEY="$PUB"` set, the same check is made on each answer during the run, and the action trace says `Signature: verified`. Keep a receipt to text, whole numbers, true, false and null: the signature is over the receipt without its `signature`, as JSON with sorted keys and no whitespace (ADR 0041).

If your receipts are signed another way, with another algorithm, canonical form or envelope, give your own verifier in place of a key: `--verifier "my-verify --strict"`. It is run once for each receipt line, with the line as JSON on standard input, and verifies it by exiting with status 0. What the receipt says is still checked against the run here; whether it is authentic is then yours to say.

If your integration needs new context or identity material, describe the missing field or behavior in an issue. You can identify your system when you choose to participate.

## What all of them get

- Matched scenarios, agents, seeds and oracle. A deterministic adapter and fixed inputs make the comparison reproducible.
- A first result in minutes (`--tier quick`) and a full one in a few hours on one machine (`--tier standard`). See [tiers](../bench/TIERS.md).
- Their own figures beside the built-in gates', under [rules that keep different kinds of gates comparable](../bench/FAIRNESS.md).

## What the result establishes

Agentic-Datacenter measures the consequences of decisions on a simulated plant. Identity verification, receipt authenticity and authorization each require evidence appropriate to the system being evaluated. Keep those claims distinct from the simulator's measurements.
