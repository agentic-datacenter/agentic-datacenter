# ADR 0048: A site declares how it reads a delegation

- **Status:** Accepted on 2026-11-27, for the rule, its vectors and the reference verifier. A scenario that declares its model is for the next frozen version.
- **Date:** 2026-11-27
- **SDD:** 9.4; ADR 0039, 0040, 0042
- **Proposed in:** [issue 76](https://github.com/agentic-datacenter/agentic-datacenter/issues/76), by aeoess

## Context

The rule for signed mandate statements reads a delegation by what its issuer holds now (ADR 0040). The first tester from outside compared the reference verifier with a system of his own and found two cases where they part:

1. An operator withdraws an orchestrator's mandate and later gives it again. The agent the orchestrator had passed it on to has its mandate back, with no new statement to the agent.
2. An orchestrator passes on more than it holds. Later it is given the rest. The agent then holds what was passed on beyond the orchestrator's mandate at the time.

Both follow from the rule as written. A system that binds each delegation to the grant it was issued under refuses in both, and has reasons to: a withdrawal that can be undone without anyone telling the agent is not what "withdrawn" means to every operator, and an overbroad delegation that becomes good later was never checked by anyone.

Neither reading is wrong. They are two models a site may have. A benchmark that held every system to one of them would fail the systems of the other for being consistent.

## Decision

**A site declares its model.** Two to begin with: `holdings`, the rule as it was, and `grant_bound`.

**`grant_bound` needs no new field.** The grant a delegation was passed on under is the statement that was the head of its issuer's chain when the delegation was issued; a verifier has every statement of that chain already. The delegation holds while that statement is still the issuer's head, and only if it lists nothing the grant did not. So the statement format, the bytes signed and every existing test vector are unchanged.

**A delegation that lists more than its grant gives nothing.** Not the part within the grant either. A statement that claims more than its issuer held was not checked when it was made, and what it may be relied on for is the site's to decide by having it issued again.

**A third kind of "no".** `unbound`, beside `ended` and `never_held`, for a delegation that is not under the grant its issuer holds now.

**Vectors under both models.** `docs/reference/mandate-vectors-grant-bound.json` gives every case twice on the same statements, so the two models are told apart by what they do and a system can run the one it follows. It is under the MIT licence with the other vectors. The reference verifier reads a case's `model`.

**The default is unchanged.** Everything that does not name a model reads `holdings`, and every hash and every vector of the frozen benchmark is as it was.

## What is not built

- **No scenario declares a model.** A run is judged by the register, and the register reads `holdings`. Letting a scenario declare `grant_bound` changes what a run is judged by, which is the judge of a frozen version. It comes with the next one, with the two cases above as scenarios, and from then on as kinds of the weekly generator.
- **A gate is not yet told the model.** A request will carry it beside the statements from the version in which a scenario can declare it.

## Consequences

- A system that binds delegations to grants can check itself against vectors today, and is not wrong by this project's rule for being stricter.
- The reading a site declares is one more thing a system has to get right, and the benchmark can tell a system that follows the site from one that follows only its own habit.
- Two models are two to maintain. A third is added only when a system that uses it asks.
