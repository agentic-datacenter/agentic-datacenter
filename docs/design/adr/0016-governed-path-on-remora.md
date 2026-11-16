# ADR 0016: The `GOVERNED` and `SHADOW` profiles on REMORA's execution service

- **Status:** Accepted for `inproc` mode. Decisions 2, 4 and 7 are readings of the design that need the owner's confirmation.
- **Date:** 2026-11-13
- **SDD:** 5.2, 9.2, 9.6, 13 (Stage 8); requirements `ADC-GOV-001`, `-002`, `-006`, `-007`, `ADC-PIN-003`, `-005`

## Context

Stage 8 puts REMORA's governed execution path behind the gate interface. Its entry condition was a pin with `remora sign-limits`, `export-contract-files` and `build-toolspec`; the last arrived with REMORA #1232, together with a way to hand over the observed effect through the SDK.

Before any code was written the path was driven end to end from a host that imports `remora.sdk` only (17 of 19 steps passed; the two that did not are below). What that showed decides most of this ADR.

## Decisions

1. **The service runs in this process, behind the SDK client.** `RemoraClient` speaks REST. In `inproc` mode it is given an HTTP client bound to REMORA's application object, `servers.api:app`, which is REMORA's documented entry point (`uvicorn servers.api:app`). That object is the one thing loaded outside `remora.sdk`, by name, in one place; the public-surface test names it. Everything else is configuration: environment variables, three compiled files, and two small modules REMORA is told to import (`agentic_datacenter_remora.host_registry`, `agentic_datacenter_remora.sim_clock`). `agentic-datacenter-remora` now needs REMORA's `api` extra.

2. **One service per process; runs are kept apart by name.** REMORA reads its configuration when its application module is imported, and has no public way to build a second one or to reset the first. A process therefore governs one contract library. Runs in the same process share one tenant, and each run puts its own name in front of every resource a limit is kept under, so their counters never meet. The audit chain is shared and stays valid across them.

3. **Time is simulated time.** `REMORA_TIME_SOURCE_MODULE` names `agentic_datacenter_remora.sim_clock`, which the gate sets from the kernel clock before every call. Token and approval expiry, limit windows and audit timestamps are then on simulated time, with 2000-01-01T00:00:00Z as time zero. REMORA refuses a host clock in production, so the service runs as `development`; approver separation, which production implies, is switched on explicitly.

4. **A bounded, reversible R1 step runs without a person; everything else goes to one.** *(Revised 2026-11-13 on pin `dcsim-pin-2026-11-13b`.)* At the first Stage 8 pin REMORA accepted no write without a person (REMORA issue 1233), so every write under `GOVERNED` waited for an operator: 143 approvals per simulated day with the benign agent in the first test round. REMORA #1234 added an opt-in deterministic path, `bounded_write_accept`, that accepts a write only when its action type is exactly `write`, its tier is `low`, a rollback is declared, its arguments are schema-valid, the target is not production, and two facts only REMORA's server sets hold: the signed ToolSpec is enforced for the tool and a cumulative-limit meter governs it. Every refusal of any other check still wins; an accept past a limit's `dual_control_above` is still lowered to two approvers; the reservation at dispatch still charges and can refuse. Agentic-Datacenter switches the path on and declares each contract at the tier that matches it: an R0 or R1 contract with a rollback is `low`, every other executable contract is `high` and goes to a person with the role REMORA asks for at that tier (`domain_expert`). REMORA also refuses to start when the tool metadata and the signed ToolSpec disagree on action type or tier, so the declaration cannot be relabelled after signing. **Reading for the owner to confirm:** the path normally also requires a resolved intent authority. Agentic-Datacenter has no intent source a host can supply through `remora.sdk`, so it sets `REMORA_BOUNDED_WRITE_REQUIRE_INTENT=0`. Without it, an automatic step is bounded by the contract, the limits and the rollback, but not tied to a work order. The approval a contract names on its own terms (`one_operator`, `two_person`) is unchanged.
5. **A contract becomes one tool.** `agentic-datacenter contracts compile` writes a ToolSpec bundle with one tool per executable contract and signs it with `remora build-toolspec`; the limit policy is signed with `remora sign-limits`. The tool's arguments are the contract's, plus `target`, the first point written, which the binding fills in from the control path's own reading.

   | Contract field | Where it is enforced under `GOVERNED` |
   | --- | --- |
   | Bounds (`min`, `max`), choices | Signed ToolSpec argument schema |
   | Rate | Signed limits: a count per written point per hour |
   | Cumulative limit | Signed limits: movement of the first written point, in thousandths of its unit, shared by every contract that writes that point (`INV-GOV-6`) |
   | `two_person` | Signed limits: `dual_control_above: 0` on the contract's counter |
   | `max_step`, premises, rollback, writes after the first | The binding and the control path, as in every profile; listed per contract in the compile manifest |

   A contract that would be left without a bound anywhere fails the build: an unbounded numeric write, an authoritative text argument, a limit that is not a whole number of ledger units.

6. **Signing seeds and credentials are derived, not drawn.** The SDD derives the limit-signing seed from the run seed. With one service per process the artifacts cannot follow the run, so every simulator-only secret (two signing seeds, four service keys, the bearer tokens) is a hash of a fixed label and the contract library. The same library gives the same signed bytes; nothing is written to disk but the public halves. `--new-key` is never used.

7. **What goes into the state hash.** The decision reference is a hash of Agentic-Datacenter's proposal id, the verdict, the writes, REMORA's reasons and the tool-call hash of the pure decision. REMORA's proposal id, grant, tokens and audit hashes are drawn at random by design; they stay in the gate and go to the evidence bundle (`gate_evidence.json`) with the result of verifying the audit chain. Two runs of one seed give the same state hashes.

8. **Execution is released by the gate.** The gate interface gains optional hooks, looked up by name so that a gate without them is unchanged: `approve`, `reject`, `execute`, `resolve_unknown`, and the flag `enforces_limits`. Under `GOVERNED` the control path hands `execute` a function that performs the command-service writes; REMORA calls it at most once, from inside its dispatch, after consuming the grant. If REMORA refuses, nothing is written. After a successful write the point is read back and the observation handed to REMORA, which computes the effect verdict itself.

9. **Unknown outcomes.** A write the command service does not answer is recorded as `UNKNOWN` in every profile, is never sent again on that grant, and is resolved thirty simulated seconds later from a read of the plant: all writes in place is applied, none is rejected, some is restored and recorded as rolled back. Under `GOVERNED` the same finding is given to REMORA by a reviewer principal that is not the agent, through the evidence module REMORA checks. A write the command service refused outright is resolved the same way at once, because a host cannot yet state non-execution through the SDK (issue 1233).

10. **Counterfactual replay.** REMORA's ledgers cannot be put back to an earlier instant. For a gate that says so (`restorable = False`) a counterfactual branch is played from the start with the decision forced, which the same seed makes identical up to that decision.

## Consequences

- `GOVERNED` and `SHADOW` exist as gates `remora_governed` and `remora_shadow`. Both refuse to start unless the installed REMORA is the pinned commit.
- `AD-04` (replay), `AD-05` (drift) and `OP-13` (unknown outcome) can be claimed under `GOVERNED`; they could not under `DECISION_ONLY`.
- Under `GOVERNED` an R1 step with a rollback runs without a person; R1 without a rollback and every R2 contract wait for one. The approval count is on every result card.
- One contract library per process means a benchmark over several libraries needs several processes.

## Not done

- `compose` mode against a REMORA service in a container.
- A semantic bundle and an intent source, as REMORA's pilot uses. They need types outside `remora.sdk`.
- Asynchronous dispatch. A pending execution is treated as unknown.
- The SDD still says the seed comes from the run seed and that R1 is automatic; both sentences are corrected in the same pull request as this ADR.
