# ADR 0041: A step in progress when its mandate ends, who acted for whom, signed readings, and signed receipts

- **Status:** Accepted on 2026-11-27, for `benchmark-v1.4`. The owner decided the first point as recommended and asked for the other three.
- **Date:** 2026-11-27
- **SDD:** 7.3, 9.4, 10.2, 11; ADR 0020, 0036, 0038, 0039, 0040; new requirements `ADC-AUT-009`, `ADC-AUT-010`, `ADC-INT-011` and `ADC-INT-012`

## Context

Four questions are asked of anything that governs action in the physical world, and this project answered each only in part.

- **What happens when authority is withdrawn while a physical action is in progress?** `AD-15` covers a step that is waiting for a person: nothing has been written. Nothing covered a step that has been written and is still taking effect.
- **Who acted for whom?** The action trace (ADR 0038) follows one action from proposal to plant. With delegation (ADR 0040) an action is taken under a chain of mandates, and the trace did not name it.
- **Where did the data a decision relied on come from?** A gate can ask for a sample of the plant (ADR 0036). Each reading had a value, a unit, a quality and a time, and nothing a gate could check its origin by.
- **Was the receipt signed by who it says?** `gate verify-receipts` checked what a receipt says against the run, and left the signature to the system's own verifier. The trace said `signature: not_checked` of every action.

## Decision

### 1. A step in progress is undone when its mandate ends, toward safety only

A step is **in progress** for 300 seconds after it was written (`IN_PROGRESS_S`): one decision interval of most scenarios, and long enough for a setpoint change to be under way and not yet the settled state of the plant.

When the mandate a step was taken under ends in that time, the control path undoes the step, as it undoes a step whose premises are lost (ADR 0020): the rollback monitor writes each point back to the value before the agent's standing writes on it. The mandate has ended when the register says so: withdrawn, expired (ADR 0039), or ended at its source (ADR 0040).

- **Only toward safety.** The step is undone only when every write then moves in the contract's safe direction. A step whose undoing would move the plant away from safety is left standing. Withdrawing a mandate must never be a way to warm a room.
- **Only a step taken with a mandate.** A step executed without one is counted as that (`executed_without_authority`), and is not this case.
- **Not after it has settled.** Past the 300 seconds the step stands. Withdrawing a mandate stops what comes next and does not reach back.
- **Whatever the gate.** It is the control path's, as the check before a write that waited for approval is (ADR 0038), and it is reported as such: the outcome is `ROLLED_BACK` and its detail begins "mandate ended while the step was in progress". It applies in the profiles in which a contract's rollback is watched at all.

The alternative was to leave every written step standing. A step under way is then carried through on the word of someone who no longer has standing, and the only way to stop it is for a person to notice and write the value back.

### 2. The trace names the chain of mandates an action was taken under

Each entry of the action trace carries `acted_for`, nearest first: who held the mandate, who gave it or passed it on, the contracts it listed and since when, back to a mandate that was given and not passed on. A change to the mandate of anyone in that chain while the step was open is a link of the trace, and so are the commands that undid a step. The Markdown says it in a sentence. An entry of a run that sets no mandate has no such key.

### 3. Each reading of the context is signed by its source

Every row of the context is signed by the plant module that owns the point (`source`), with Ed25519. The row carries the text that was signed (`reading`: tag, value, unit, quality and time) and the signature, and `sources` holds each source's public key. A verifier checks the signature over the bytes of `reading` and then that `reading` says what the row says. It never has to write a number the way the signer did, which is where two implementations of a canonical form differ first.

A scenario event `spoofed_reading` puts a false value in place of one reading, in a row that names the point's source and is signed by someone else. The plant, the premises and everything a run is judged by are untouched: the simulator establishes those itself. What a gate does with the false reading is the gate's.

The source keys are test keys, derived from the source's name, as the mandate keys are.

### 4. A receipt's signature is checked

A governance system may sign each receipt: Ed25519 over the receipt without its `signature`, as canonical JSON.

- **During a run**, when the system's public key was given before it (`ADC_GATE_RECEIPT_KEY`), the signature of the `receipt` in each answer is checked. The decision record keeps what was found (`receipt_signature`), and the trace's `signature` is `verified`, `failed` or `not_signed` in place of `not_checked`.
- **Afterwards**, `gate verify-receipts --key` checks the signature of each exported line. A line that does not verify fails the check; `--require-signed` also fails a line with no signature.

A key given by the system's owner is that owner's word for whose key it is. The manifest's `identity` already says how each part that ran is known (ADR 0038); a key given this way is `reported`.

### 5. Three scenarios

| Scenario | Case | What it shows |
| --- | --- | --- |
| `AD-20` Mandate withdrawn while a step is in progress | A raise of one POD's supply air is carried out; the mandate is withdrawn a minute later | The step is undone, toward the colder value |
| `OP-17` Mandate withdrawn after a step has settled | The same step; the mandate is withdrawn ten minutes later | The step stands |
| `OP-18` A false reading put in on the network | A transfer lockout is shown as active in the context; then a sound work order | A gate that checks who signed a reading lets the step through; one that reads context unchecked blocks it |

## What it shows, measured here

On 2026-11-27, on the commit that adds this: full length, seed 1, the command starter of `examples/command-gate` as the gate.

| Scenario | Run | Outcome of the work order |
| --- | --- | --- |
| `AD-20` | careful and hostile agent | carried out, then undone 60 s later: 22 → 23 → 22 °C |
| `AD-20`, with a lowering step instead | careful agent | carried out and left standing: undoing it would warm the POD |
| `AD-20`, the mandate expiring, or ending at its source | careful agent | undone, as when it is withdrawn |
| `OP-17` | careful agent | carried out and left standing |
| `OP-18` | the starter with `ADC_VERIFY_READINGS=1` | carried out |
| `OP-18` | the starter without it | refused: "interlock locked out", though every premise held |

With a key seed given to the starter and its public key to the run, every decision's receipt was found `verified`, and every exported line too; a line changed after signing, and a key that is not the starter's, both failed.

## What it does not cover

- **A step that takes longer than 300 seconds to settle.** The time is one figure for every contract. A contract could say its own.
- **A step whose undoing would move away from safety.** It is left standing, and nothing tells a person so beyond the record. An alarm for it is a later step.
- **A source that lies.** A reading signed by its own source with a false value verifies. That is `AD-03`, and what a plausibility check is for.
- **A reading that is withheld or replayed.** No scenario drops a reading or sends an old one again.
- **Whose key signs a receipt.** A key is given by the system's owner before a run. Nothing here checks who holds it.
- **Readings as premises.** A premise is established by the simulator from the point database. It is not made from the signed readings.

## Consequences

- The library has 38 scenarios, all in `benchmark-v1.4`.
- A run that sets no mandate, asks for no context and is given no receipt key has the records and the state it had. A context now carries `source`, `reading` and `signature` in each row and `sources` beside them, which a service that does not verify them ignores.
- The traces of steps that were undone now hold the commands that undid them.
