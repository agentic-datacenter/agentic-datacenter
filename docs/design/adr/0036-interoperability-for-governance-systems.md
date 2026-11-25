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

The session names one execution: it differs between two executions of the same run, and between one process and many. `gate_detail` is therefore kept on the record and left out of the control path's state. State hashes, cards and their reference copies do not depend on it (ADC-BEN-006). The evidence bundle's `decisions.jsonl` and the `decisions.jsonl` beside a card carry it.

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

`agentic-datacenter gate verify-receipts <bundle or decisions.jsonl> <receipts.jsonl>` reads the receipts a system exported, one JSON object per line, merged by `correlation_id`. For each, every field it gives of `action_ref`, `verdict` (a word of the system's own read as the verdict it means), `outcome` and `decision_id` must be what the record holds. Each record's `action_ref` is made again from the record, so a record changed after the run is found. It reports receipts that match, that do not and why, that name no decision, and decisions without a receipt (`--require-all` fails on those). It checks no signature: that is the system's own verifier's work, and the next step (ADR 0037).

The MIT command starter writes such receipts when `ADC_RECEIPTS_FILE` is set, and refuses a step while an interlock is locked out when it is given the context.

### 6. Nothing named

The guides describe capabilities, not projects. A system identifies itself when it chooses to take part.

## Consequences

- A system that issues receipts can show, from a run anyone can repeat, that each of its receipts belongs to the right proposal and outcome.
- A system that reasons about the site has temperatures, load and interlocks with their units, quality and time.
- Requests are larger by the correlation, and with the context by some fifty points. The wire format stays `agentic_datacenter.gate.http/1`: every new field is optional to read, and the request had no closed set of properties.
- Signed mandates, signature checks and conditional permissions are not part of this decision. They change what is judged and belong in a benchmark version (ADR 0037).
