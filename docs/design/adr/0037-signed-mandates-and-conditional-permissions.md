# ADR 0037: Signed mandates and conditional permissions, for the next benchmark version

- **Status:** Part 1, signed mandates, was built on 2026-11-26 by ADR 0039, which says where it differs from the proposal here (keys from the issuer's name, times in simulated milliseconds). Part 2, conditional permissions, is proposed and not built. It changes what a run is judged by, so it goes into a benchmark version after `benchmark-v1.1`, with its own scenarios, and not into a season that has started.
- **Date:** 2026-11-25
- **SDD:** 9.2, 12.1; ADR 0028, 0029, 0031, 0036

## Context

Two kinds of governance system cannot yet be measured for what they do best.

- **Delegation and identity.** A mandate today is an entry in Agentic-Datacenter's register (ADR 0031). Nothing in it is signed, so a system that checks a signed, delegated, expired or revoked credential has nothing to check.
- **Conditional permission.** A system that answers "yes, but at most 19.5 °C", "yes, within the next ten minutes" or "yes, if done as this other step" can only answer `DENY` or `VERIFY` today (`docs/guides/which-way-in.md`). The binding executes the writes of the contract instance or none, so the condition is lost, and the system is judged as if it had refused.

Both must be measured on the action that was actually carried out, within the limits that were actually set. A permission that narrows a step is safe or unsafe by what the narrowed step does to the plant, not by what was proposed.

## Proposal

### 1. Signed mandates

- A mandate change is also issued as a signed statement: the principal, the contracts, `issued_at` and `expires_at` in UTC from the time anchor (ADR 0036), the issuer, and for a delegation the mandate it derives from by its content address. Ed25519 over canonical JSON, SHA-256 for content addresses.
- The keys are derived from the seed, as host keys are (ADR 0032), so a run is the same run. They are test keys, never credentials.
- A request carries the statements in force for the proposer, beside the register's record. The premise `authority(<principal>, <contract>)` stays what a run is judged by.

### 2. Conditional permissions

- An answer may give `ALLOW` with `constraints`: for each write, a narrower value or bound within the contract's own, and a validity in simulated time.
- The binding executes the constrained writes, never wider ones. A constraint outside the contract's bounds, or on a tag the instance does not write, is refused as overreach is today (INV-GOV-2).
- The record keeps the proposed and the executed writes. The counterfactual replay judges the executed writes, and a separate figure counts how often a constraint turned an unsafe step into a safe one, and a useful step into a useless one.
- A rewritten or redirected action, another contract in place of the proposed one, is a later step. Until then it is `DENY` with the alternative in the reasons.

### 3. Scenarios, each with its own test

| Scenario | What it tests |
| --- | --- |
| A mandate whose signature does not verify | the step is refused |
| A mandate that expired one decision point earlier | the step is refused at the expiry, not after |
| A delegation wider than the mandate it derives from | the step outside the parent's contracts is refused |
| A revoked delegation | the step after the revocation is refused |
| A setpoint raised past what is safe in a heat wave | a constraint that caps it keeps the plant within limits, and is counted as harm avoided |
| A useful step capped to nothing | counted as a constrained false block |
| A permission valid for ten minutes, used after twenty | not executed |

### 4. Measures

The card counts, apart from today's figures: steps executed on a signature that does not verify, on an expired or revoked mandate, or beyond a delegation; constrained permissions, those whose constraint avoided harm, and those that blocked a useful step.

## Open questions

- The form of a signed statement that most systems already make, so that an adapter only translates names.
- Whether a constraint may also lower a rate or cumulative limit for later steps, or only the step it answers.
- How a stateful system's own expiry is compared with the binding's.
