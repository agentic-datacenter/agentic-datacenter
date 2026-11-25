# ADR 0036: Correlation, a fixed time anchor and plant context, for governance systems from elsewhere

- **Status:** Accepted on 2026-11-25. The owner asked for the threshold for other governance projects to be as low as it can be, without naming any of them in this repository.
- **Date:** 2026-11-25
- **SDD:** 9.2, 9.3, 12.1; ADR 0011, 0021, 0028, 0031; requirements `ADC-GOV-004`, `ADC-UX-009`, new `ADC-INT-001` to `ADC-INT-006`

## Context

A governance system connects as a gate: a package, a service over HTTP, or a command per decision (`examples/command-gate/adapter.py`). Three things made the step harder than it needs to be for systems that issue receipts or attestations, check delegation, or rely on the physical state of a site:

1. **A receipt could not be tied to its proposal and outcome.** The `evaluate` request had no identifier the `outcome` message also carried, and the service's own `decision_id` was put on the decision but kept on no record, although the guides said it was.
2. **Time was only simulated milliseconds.** A library that checks time-bounded evidence wants a date.
3. **The plant was not visible beyond the proposal.** A gate saw the premises the contract names and the writes. A system that weighs temperatures, load or interlocks had nothing to read.

The names of fields used by such systems vary. Common ground is a content-addressed reference to the action, a signed or at least stated issue time in UTC, SHA-256 over canonical JSON, and a context of the physical environment with its source stated.

## Decisions

### 1. One correlation for request, outcome and receipt

Every `evaluate` request carries `correlation`:

| Field | What it is |
| --- | --- |
| `correlation_id` | `<session>/<proposal_id>` |
| `action_ref` | `sha256:` and the hex SHA-256 of the canonical JSON (keys sorted, no whitespace, UTF-8) of `session`, `proposal_id`, `contract_id`, `arguments`, `principal` and `time_ms` |
| `issued_at` | `premises.time_ms` as UTC from the time anchor, to the millisecond |
| `time_anchor` | the UTC instant simulated time 0 is given as |

The `outcome` message carries the same `correlation_id` and `action_ref`, and the `proposal_id` and the verdict read from the answer. For an outcome of a decision the service was not asked about, such as a step the counterfactual replay blocks, they are null.

An answer may give `decision_id` and a `receipt` object (at most 16 KiB in canonical JSON). The decision record keeps them, with the correlation, in `gate_detail`. The record of a built-in gate has no `gate_detail` and is what it was.

### 2. Kept out of the state

The session names one execution: it differs between two executions of the same run, and between one process and many. `gate_detail` is therefore kept on the record and left out of the control path's state. State hashes, cards and their reference copies do not depend on it (ADC-BEN-006). An evidence bundle keeps it apart, in `correlation.jsonl`, which its manifest names as `execution_specific` and does not hash, so the same run gives the same bundle bytes; its `decisions.jsonl` is the records without it. The `decisions.jsonl` beside a card carries it on each line.

### 3. A fixed time anchor

`issued_at` and every `observed_at` count from `2026-01-01T00:00:00Z`, or from the instant in `ADC_GATE_EPOCH`. It is fixed, never the wall clock, so a run is the same run.

### 4. Plant context, read-only and asked for

A service started with `ADC_GATE_CONTEXT=1` is sent `context` with each request (`agentic_datacenter.context/1`):

- `temperatures`: the supply air of every POD and the chilled water supply;
- `load`: the IT demand of every POD and the chiller load;
- `interlocks`: lockouts, and the state of chillers, generators and power trains;
- `redundancy` and `alarms`, as an agent sees them;
- `permits`: `{"modelled": false, "items": []}`. Work permits are not modelled as points in this version, and the context says so.

Every point has `tag`, `value`, `unit`, `quality`, `time_ms` and `observed_at`. `resolution_source` is `simulated_point_database`: the values are what the simulator's point database held, as an operator's screen would show them. They are not attested by a sensor, and nothing in the context is signed. The context changes nothing the binding enforces, and a gate that does not ask for it is sent none.

### 5. A local check of receipts

`agentic-datacenter gate verify-receipts <bundle or decisions.jsonl> <receipts.jsonl>` reads the receipts a system exported, one JSON object per line, merged by `correlation_id`; two lines of one id that disagree on a field are a mismatch. Each receipt must give `action_ref` and `verdict`, and may give `outcome` and `decision_id`; each must be what the record holds, the verdict compared with what the service answered before the binding's own checks (`answered_verdict`). Each record's `action_ref` is made again from the record, so a record whose action was changed is found; for an evidence bundle, the bundle is first checked against its manifest, so a verdict or outcome changed in it is found too. A correlation id on two records is a mismatch. It reports receipts that match, that do not and why, that name no decision, and decisions without a receipt (`--require-all` fails on those). It checks no signature: that is the system's own verifier's work, and the next step (ADR 0037).

The MIT command starter writes such receipts when `ADC_RECEIPTS_FILE` is set, and refuses a step while an interlock is locked out when it is given the context.

### 6. Several systems at once

`chain_gate`, configured by `ADC_CHAIN_FILE`, puts several systems in front of the same actions, as a pilot would: commands, services or installed gates. Every member is asked about every proposal, with its own session and correlation. The strictest verdict decides (`DENY`, then `ABSTAIN`, then `VERIFY`, then `ALLOW`); an `ALLOW` stands only when every member allowed the same writes. The record keeps each member's verdict, reasons and correlation, and whether it was decisive. Each member is told the outcome of its own decision. A gate that authorizes execution itself cannot be a member.

### 7. A summary to read, and testing that keeps going

Every card is written with `summary.md` beside it: each gate's figures in plain words, one column per agent, the built-in gates marked, and how to check the result. `examples/ci/agentic-datacenter.yml` (MIT) is a workflow a maintainer copies into their own repository: on every change and every week it checks out a chosen version of this project beside theirs, runs the interface check, one run with its receipts and a quick benchmark beside the built-in gates, puts the summary on the run's page, and fails on a harmful step let through. `docs/guides/for-governance-maintainers.md` says what a maintainer gets, what it costs, what it does not give, and why a benchmark whose owner also owns a gate can be trusted.

### 8. Nothing named

The guides describe capabilities, not projects. A system identifies itself when it chooses to take part.

## Consequences

- A system that issues receipts can show, from a run anyone can repeat, that each of its receipts belongs to the right proposal and outcome.
- A system that reasons about the site has temperatures, load and interlocks with their units, quality and time.
- Requests are larger by the correlation, and with the context by some fifty points. The wire format stays `agentic_datacenter.gate.http/1`: every new field is optional to read, and the request had no closed set of properties.
- Signed mandates, signature checks and conditional permissions are not part of this decision. They change what is judged and belong in a benchmark version (ADR 0037).
