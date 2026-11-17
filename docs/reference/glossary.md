# Words used here

| Term | Meaning |
| --- | --- |
| Gate | The system under test. It decides on each proposal an agent makes and never writes to the plant itself. |
| Verdict | A gate's answer: `ALLOW`, `DENY`, `VERIFY` (a person must approve first) or `ABSTAIN` (the evidence is missing, stale or contradictory). Only `ALLOW` and `DENY` are required. |
| Contract | What a kind of action may do: its bounds, step size, premises, approvals and limits (`contracts/`). |
| Operating profile | What a gate may do: decide only (`DECISION_ONLY`), decide and execute (`GOVERNED`), watch only (`SHADOW`). Results are always shown beside it. |
| Counterfactual replay | Each refused proposal is replayed as if it had run, to show whether refusing it avoided harm or cost a useful step. |
| False block | A refused step that would have been safe and useful. |
| Required block | A refusal the contract itself demands, such as a rate limit. Not counted as a false block. |
| Invariant | A rule that holds in every run whatever the gate ([Invariants](invariants.md)). A breach refuses the result card. |
| Tier | How large a benchmark run is: `quick`, `standard`, `season` or `full` ([Tiers](../bench/TIERS.md)). |
| Result card | The JSON a benchmark writes: safety, false blocks and approvals per gate and agent. |
| `bench check` | Refuses a result card in which harm got through, an invariant was breached, or that is incomplete ([Release check](../guides/release-gate.md)). |
| Development run | Any run with `--allow-unfrozen` on a version that is not frozen. It cannot be reported as a benchmark result. |
| Season | A public test on one frozen benchmark version, with hidden variants drawn from a public beacon ([Public test](../bench/PUBLIC_TEST.md)). |
| Track D | The hidden variants of a season. Nobody can know them before the beacon round. |
