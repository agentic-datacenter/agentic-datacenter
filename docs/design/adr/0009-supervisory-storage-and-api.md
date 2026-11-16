# ADR 0009: Supervisory storage and API in Stage 5

- **Status:** Accepted with the Stage 5 PR.
- **Date:** 2026-11-12
- **SDD:** 5 (technology choices), 7.5, 8.3; requirements `ADC-SUP-001` to `-005`

## Context

Section 5 names SQLite and Parquet for the historian and FastAPI over mutual TLS for the operator API, "the same service in both run modes". Section 8.3 gives the body of a command as tag, value, actor, role, reason and an optional decision reference. Section 7.5 says there are four permission levels and does not name them.

Stage 5 runs in `inproc` mode only; `compose` mode, real sockets and certificates arrive in Stage 6. Counterfactual replay restores the simulation state thousands of times per benchmark run.

## Decision

1. **The historian keeps its data in memory** and is not part of the simulation state or its hash. What it holds is a pure function of the run, so nothing is lost for reproducibility, and a restored run cuts the history back to its own time. Writing history to SQLite and Parquet is done where files are wanted: the evidence bundle of Stage 9. No Parquet library is added before then.
2. **Energy records are integrated from power.** The plant modules expose power, not energy meters. Every fifteen minutes the historian writes the kWh of IT load, facility, chillers, pumps, fans and UPS losses, summed from one-second power readings, with the worst quality seen in the interval.
3. **The API is one FastAPI application built from the supervisory layer** (`agentic_datacenter.supervisory.api.create_app`). In `inproc` mode it is called directly. Mutual TLS is a property of the deployment and is added with `compose` mode in Stage 6. The API never advances simulated time.
4. **Who a command acts as comes from the session, not from the body.** A body that names an actor or a role is refused. This follows `INV-GOV-5` (identity is taken from the credential) and differs from the body listed in section 8.3; a change to that sentence is proposed.
5. **The four permission levels are** `viewer`, `operator`, `engineer` and `administrator`. The agent is a principal with its own rule (a decision reference for every write), not a fifth level.
6. **Session tokens are drawn from the run's random stream**, and the simulator's users and secrets are fixed and public. A run is then reproducible, and nothing here can be mistaken for a credential.
7. **The alarm engine and the derived alarm view coexist for now.** The engine (states, deadbands, suppression, log) serves operators through the API. Premises of the form `no_active_alarm(...)` and the agent's `list_alarms` tool still read the stateless view in `overview.py`. Both read the same points. Stage 8 moves the premises to the engine, when the gate interface is reviewed as a whole.

## Consequences

- A benchmark run pays for the alarm engine (one scan per second) and not for the historian, which the scenario harness does not build.
- The Starlette test client warns that `httpx` is deprecated in favour of a package that section 5 does not list. The warning is filtered in the test configuration; the client is used in tests only.
- Section 8.3 needs one sentence changed (decision 4), and section 7.5 could name the levels (decision 5).
