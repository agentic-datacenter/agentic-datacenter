# ADR 0019: What-if, one proposed change played as three branches

- **Status:** Proposed. Accepted when the PR that adds it is merged by the owner.
- **Date:** 2026-11-13
- **SDD:** 5 (distributions and layers), 9.2 (binding surface), 9.6, 10.4, 11 (`ADC-WIF-001` to `-005`), 12.2; ADR 0016

## Context

An owner considering a change to the plant, the first one being a chilled water supply setpoint of 20.5 °C instead of 18.0 °C, asks three questions that the benchmark does not answer directly: what does it save, which physical margins does it use up, and can the AI agent carry it out under its contract and the gate, and if not, why not. The answers have to be reproducible and carry their evidence, and they must not blur the line the rest of Agentic Datacenter draws between what the plant would do and what the agent is allowed to do.

Three things make that hard to do with the existing commands:

- A benchmark run measures a gate with a fixed agent. It never shows the physics of the change itself, separately from whether the change was allowed.
- Showing the physics of a change the contract does not allow needs a way to put the plant in that state without pretending that a gate allowed it.
- The question "why can the agent not do it" has two different answers: the contract's published limits, which Agentic Datacenter checks, and REMORA's policy, which only REMORA can analyse.

## Decisions

1. **A new distribution, `agentic-datacenter-whatif` (`agentic_datacenter.whatif`), above the harness.** It imports `core`, `supervisory`, `governance` and `scenarios`, plus `pydantic`, `PyYAML` and `FastAPI`, all already in section 5 (FastAPI is used by `agentic-datacenter-supervisory`). No new dependency. The harness does not import it, and no lower layer does (import contracts). The package installs, type-checks and passes its own tests without REMORA.

2. **Three branches from one start state.** Every branch is a `ScenarioRun` of the same what-if scenario, profile, contract library and seed. The state hash after the warm-up, before anything differs, is recorded for each branch and must be equal; the run refuses to report otherwise.

   | Branch | Operating profile | How the change is made |
   | --- | --- | --- |
   | A baseline | `BASELINE_RULES` | It is not |
   | B physical | `BASELINE_RULES` | A simulator-internal override writes the target to every point the contract writes, on the module's own I/O board, at scenario time zero, and puts it back if anything moves it. It never goes through the Supervisory Command Service, never carries a decision reference and is never an agent action; the branch is labelled hypothetical in every output |
   | C governed | `GOVERNED` (`remora_governed`) | A goal-seeking agent, a new class in this package and not one of the benchmark agents, proposes contract instances toward the target through the agent tool surface |

   The override lives in `agentic_datacenter.whatif`, not in a plant module and not in the command service, so it cannot be reached from the agent's tool surface or from a protocol server.

3. **The goal-seeking agent respects published limits and says why it stopped.** At each decision point it reads the written point, the contract (`describe_contract`) and its own proposals, and proposes one step of at most `max_step` toward the target only when the contract's rate and cumulative limits leave room. It records every decision point: proposed (with the gate's verdict, outcome and REMORA's reasons) or held back (rate limit, cumulative limit, target reached). The branch reports the final value reached and the reasons it stopped short of the target. It reads premises only through what the gate records; it does not pre-filter on them, so a premise that does not hold shows up as the gate's reason.

4. **REMORA ledgers: one service, one prefix per branch, one job at a time.** Under `GOVERNED`, REMORA's service is one per process and every run puts its own name in front of each resource a limit is kept under (ADR 0016, decision 2). That is sufficient isolation for the governed branch: its rate and cumulative counters start empty and no other branch or earlier job can charge them. Only branch C uses REMORA. Because the service, its simulated clock and the host registry are process-global, the job API runs one what-if at a time on a single worker thread.

5. **Preflight and policy analysis beside the physics, never mixed with it.**
   - The **preflight** is Agentic Datacenter's own check of the change against the contract at the start state: range, step, rate, cumulative limit and the premises the change would need, read by the same code the control path uses (`build_snapshot`). It says how many steps the change takes and the most the contract allows within its cumulative window.
   - The **policy analysis** is REMORA's `what_if` on two observations of the call: the one Agentic Datacenter's binding decides on in every profile, under the library engine, and Agentic Datacenter's reconstruction of the one REMORA's execution API builds on its registry-only path, under the engine flags Agentic Datacenter's governed path sets (execution profile, bounded-write accept, intent optional). It is done for the change as one call and for its first contract step. It reports the verdict, the hard guard, and the smallest sets of facts that would change the verdict, each tagged with who could bring it about. A fact only the deployment declares (a lower risk tier, `read` instead of `write`) is labelled "requires authorised reconfiguration", never offered as an option. The analysis grants nothing: no token, no proposal, no write.
   - `what_if` reaches Agentic Datacenter through `remora.sdk` only (REMORA PR #1236, `remora.sdk.what_if` and `EngineOptions`). It is not in the current pin. The adapter in `agentic_datacenter_remora` looks for it at run time; without REMORA, or with a REMORA that lacks it, the policy part says so and is skipped. `agentic-datacenter whatif policy` produces the analysis on its own, as a separate bundle, so it can be run against a REMORA that has it without re-running the physics.
   - Only one module of the package, `agentic_datacenter.whatif.policy`, imports anything REMORA-related, and only `agentic_datacenter_remora.whatif`, lazily (import contract). REMORA itself is still imported only inside `agentic_datacenter_remora` (`ADC-PIN-001`, `-005`).

6. **Measurement.** Energy per branch (facility, IT, chillers, pumps, fans, UPS losses) is integrated from true plant state at the harness's ten-second sample, the same way `Metrics.facility_kwh` is; facility and IT kWh are the harness's own metrics. The supervisory historian also keeps fifteen-minute energy records per system, but from the point database (so a stale reading is recorded as stale), aligned to absolute simulated time and therefore offset from scenario time zero by the warm-up; it is not used for the figures. Savings are baseline minus candidate, in kWh and per cent. Cost is kWh times a price the request supplies; there is no default price and no annual extrapolation. Every figure from an F1 model is labelled a model estimate. Series are kept at fifteen-minute resolution: facility kW, chiller kW, pump kW, hottest POD supply air, the chilled water setpoint and the storage charge.

7. **Violations are split by kind.** Physical: POD minutes above the critical threshold and above the envelope, IT kWh lost, steps with both breakers of a train closed, the lowest storage charge and the hottest POD supply air. Governance: writes executed over a limit, on premises that could not be established, replays accepted and writes outside a contract. Branch B reports governance as not applicable, because nothing was proposed or written through the control path; a hypothetical branch is never counted as a governance failure.

8. **Evidence.** Each branch writes an evidence bundle in the existing format (`agentic-datacenter scenario verify` checks it), with three more files listed in its manifest: the series, the branch description and, for branch C, the agent's log. A what-if manifest at the top records the request and its hash, the code commit and package versions, the REMORA commit of each part that used REMORA, the start state hashes, and the hash of every file below it, including each branch manifest, so the whole directory verifies the same way.

9. **Scenario ids `WF-nn`.** The scenario schema accepts `WF-nn` besides `OP-nn` and `AD-nn`. What-if scenarios live in the what-if package, not in the scenario library, so the acceptance suite, the benchmark library and the frozen benchmark version are unchanged. `WF-01` is normal operation at a held 20 °C outdoor temperature for 24 h with a decision every fifteen minutes.

10. **Interfaces.** `agentic-datacenter whatif run --spec <json> --out <dir>`, `agentic-datacenter whatif policy --spec <json> --out <dir>` and `agentic-datacenter whatif verify <dir>` (entry-point group `agentic_datacenter.commands`). A FastAPI router, mounted by the host: `POST /api/v1/whatif/runs` (202 and an id), `GET /api/v1/whatif/runs/{id}`, `.../series`, `.../policy`, `.../evidence`, and `GET /api/v1/whatif/contracts`. A job id is the request hash and a sequence number; the same request always gives the same results. The router runs simulations only and takes no action on any plant; serving it follows the bind rules of ADR 0009. There is no front end in this change.

## Consequences

- An owner sees the simulated saving of a change, its physical cost and how far the agent can take it under its contract, as three labelled branches with evidence, and REMORA's own analysis of why next to them.
- A change the contract does not allow can still be studied physically, without any record suggesting it was allowed.
- The governed branch needs REMORA at the pin; without it, that branch is not run and the result says so.
- The policy analysis is unavailable until a pin contains REMORA PR #1236. The pin is not changed here.

## Not done

- Only contracts with one numeric argument that every write takes, such as the chilled water setpoint, can be studied.
- No front end; the owner's report page presents the results.
- One seed per request. Intervals over seeds, as the benchmark reports them, are not computed.

## Addendum 2026-11-14: a search the budget stopped concludes nothing negative

REMORA's `what_if` shares `max_evaluations` between four searches (model signals alone, each lever alone, the agent's levers, all levers) and reports one flag for all of them, `search.exhausted`. A search the budget stops returns what it had found, and the report turns an empty result into `False` (`reachable`, `confidence_can_lift`, `agent_alone_can_reach`) and into the text "cannot reach ... tried in every combination". Run on the adapter's own test observations with budgets of 1 to 20 against the same analysis at 20 000, 33 of 160 reports held a negative the full search contradicts. The report also does not carry a found path over to the claims it implies: with a budget of 56, the agent's search finds a path to `verify` and the report still has `reachable: false`, because the search over all levers was stopped before it got back to it.

A what-if request asks for `accept`. On these observations that search finishes within 24 evaluations at every depth a request may ask for, so a request with the default budget is not affected. Asked for `verify` through the adapter, the default budget of 20 000 covers depth 4 and stops the search at depth 5 and 6. A request may set a budget as low as 1.

1. **Each stage carries `conclusions`**, Agentic Datacenter's reading of the report: `yes`, `no` or `unknown` for `reachable`, `confidence_can_lift`, `agent_alone_can_reach` and `deployment_facts_required`, with `search_complete` and `max_depth`. A `yes` rests on a path the engine decided and holds whatever the budget. A path counts for every claim it implies: model signals are among the agent's levers, and a path of the agent's own reaches the target and needs no deployment fact. A `no` that rests on not finding something is given only when `search.exhausted` is true, and means none within `max_depth` changes. Otherwise it is `unknown`, including one from a search that may in fact have finished, because the report cannot say which one was stopped.
2. **The text follows the reading.** With a complete search `summary` is REMORA's own. Otherwise Agentic Datacenter writes it from the report: that the search was stopped, what was found, and that the rest is unknown. The one-sentence `plain` text gives a negative only for a complete search, says so when a path was found by a search that was stopped, and no longer says "every path needs a deployment fact" when a larger path of the agent's own exists.
3. **`report` stays as REMORA returned it**, so the evidence shows what the analysis said. Its booleans are read through `conclusions`; a reader that takes `report.reachable` directly still gets REMORA's answer.

The cause is in REMORA and is reported there (REMORA issue 1239); when a pin has a flag per search, decision 1 can give a `no` for each search that finished.
