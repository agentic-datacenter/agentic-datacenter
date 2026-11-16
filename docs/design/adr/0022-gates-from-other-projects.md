# ADR 0022: Gates from other projects, in any language

- **Status:** Proposed. Accepted when the PR that adds it is merged by the owner.
- **Date:** 2026-11-16
- **SDD:** 5.3, 9.2, 12.1; requirements `ADC-GOV-004`, `ADC-GOV-008`, `ADC-BEN-005`

## Context

Agentic-Datacenter exists to benchmark governance gates, and the preregistration names result cards from other gates as the intended challenge to its own. A gate could already be loaded from outside the repository through a `agentic_datacenter.gates` entry point (`ADC-BEN-005`), but only from Python, the interface suite (`ADC-GOV-004`) could be run only from a test, and nothing told an outside project how to start or how to report what it found. Most governance systems are services, and many are not written in Python.

## Decisions

1. **`agentic-datacenter gate list` and `agentic-datacenter gate check <gate>`.** `check` builds the gate through its entry point, requires an operating profile from SDD 9.6 other than `BASELINE_RULES`, and runs the interface suite. It checks the shape of what a gate returns, not whether its decisions are good; the benchmark does that.
2. **The `http_gate` binding** calls a service with one JSON request per decision and one per outcome, `agentic_datacenter.gate.http/1`, schema in `docs/reference/gate-http-v1.schema.json`. It is configured by environment (`ADC_GATE_URL`, `_NAME`, `_PROFILE`, `_TIMEOUT_S`, `_ALLOW_REMOTE`), so every process of a parallel benchmark is configured alike.
3. **What makes a decision executable stays in Agentic-Datacenter.** The service gives a verdict, reasons and, for `VERIFY`, an approver count. The writes an `ALLOW` authorizes are the instance's own, and the decision reference, nonce and expiry are made by the binding from everything decided, on simulated time. A service cannot widen an authorization.
4. **The binding fails closed.** No answer within the timeout, an answer without the schema, an unknown verdict or a verdict without reasons is `ABSTAIN`, with the reason on the decision. Such failures show as false blocks, not as harm.
5. **Loopback by default.** The requests carry simulation state, so a URL outside loopback is refused unless `ADC_GATE_ALLOW_REMOTE=1`. This is not an industrial protocol, so `ADC-SAF-002` does not apply; the default follows its intent.
6. **The binding offers no `GOVERNED` profile.** It does not authorize execution itself (the optional `approve` and `execute` hooks of 9.2); a served gate decides and Agentic-Datacenter executes, as `DECISION_ONLY`, or records only, as `SHADOW`.
7. **Templates and a result form.** `examples/python-gate` and `examples/http-gate` are each tested against the interface suite. Results are shared through an issue form that asks what was checked, by whom, what the result supports, whether the gate could forge or suppress evidence, and whether the card was written live or rebuilt.

## Consequences

- A gate's determinism is its author's: the same input must give the same answer, and a service must not carry state from one run into another, or a counterfactual replay is not a replay and a card is not repeatable.
- Every decision of a served gate costs a round trip. A long scenario under a slow service is slow; the result does not depend on it, because time in Agentic-Datacenter is simulated.
- Standard library only (`urllib`); no dependency is added.

## Not done

- No authentication between Agentic-Datacenter and the service. The service is expected on loopback, run by the person who runs the benchmark.
- A served gate cannot yet authorize execution itself or take a person's approval; that needs the hooks of 9.2 over the wire.
- No crosswalk file format. The guide asks for a mapping in prose, row by row.
