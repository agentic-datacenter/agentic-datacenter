# ADR 0029: Plants from other projects

- **Status:** Proposed. No code is written until it is accepted.
- **Date:** 2026-11-20
- **SDD:** 5, 9, 12.1; requirements `ADC-BEN-003`, `ADC-GOV-008`, `ADC-SAF-001`, `ADC-SAF-002`, and the new `ADC-PLT-001` to `ADC-PLT-006` below

## Context

The judging layer runs on the built-in plant only. That layer is the contracts, the control path, the scripted operator, the oracle, the counterfactual replay and the result card. A vendor with a high-fidelity model of their own equipment cannot ask what each gate decision does to that model. ADR 0022 opened the gate side to other projects. This ADR does the same for the plant side.

The interface below is read from what the code does today, not designed fresh. Every operation is named with the place in the code that needs it.

### How the built-in plant is reached today

One `Kernel` holds the whole run. Its 100 ms step runs the plant (`core/registry.py`, task `plant`) and the supervisory and governance tasks in the same loop:

- `supervisory.poll` and `supervisory.alarms`;
- `governance.rollback` and `governance.unknown` (`control_path.py`);
- `harness.trip_watch`.

One `kernel.snapshot()` holds the plant, the point database, the command service, the control path records and the random streams together. `ScenarioRun.capture` and `restore` (`harness.py`) are that snapshot plus the agent's and the harness's own position. There is no plant boundary in the code. These are the places that touch the plant:

| Need | Where | What it does to the plant |
| --- | --- | --- |
| Build | `build_world` | `build_plant(profile, kernel, registry)` with the run's seed |
| Points | `PointDatabase.__init__`, `read`, `declaration` | Every module's I/O board: tag, kind, tier, unit, range, description; the zone from `manifest.zone_for` |
| Write | `PointDatabase.write_through` | Sets a board value and wakes the module. Every agent, operator and rollback write goes through here, via `CommandService` |
| Step | `Kernel.run_for` in `ScenarioRun.advance` | The plant steps at 100 ms together with the tasks above |
| Inject | `apply_event` | `plant.module(id, instance).inject(fault, **params)` |
| Relay request | `_relay_request` | Finds the `electrical.mv_switchgear` instance that owns a relay and injects `remote_request` (AD-10) |
| Events | `_watch_relays` | Subscribes to `protection.trip` and `protection.refused` on the kernel bus (OP-12) |
| True state | `sample`, `finish_metrics`, `ScenarioRun.measured` | Reads module internals, not points: the true POD supply temperature (`cooling.pod`, `module.ts`), IT power served and energy lost (`electrical.it_load`), facility power (`electrical.mv_switchgear.power_balance()`), both breakers closed (`electrical.power_train`) |
| Zones | `build_network`, `zone_instances` | The zone of every instance, for the conduit model |
| Derived state | `Overview.redundancy` (supervisory) | Reads points of named built-in modules (`cooling.chw_plant`, `cooling.pump_station`, …) for the premise `redundancy.<system> >= N_PLUS_1` |
| Premise names | `premises.ALIASES` | `pod`, `tes`, `chw`, `pumps`, `eroom`, `train`, `ups`, `genset` and `it` name built-in module ids |
| Capture, restore, hash | `capture`, `restore`, `state_hash` | The kernel snapshot, which includes every module |

Three facts follow from this, and they shape the decisions.

1. **The oracle reads true state, not sensors.** Harm is measured from what the plant is, not from what the supervisory layer is shown (SDD 12). A foreign plant has to expose its true state for harm on a separate channel from its points.
2. **The contracts and the scripted agents name built-in tags.** For example `cooling.chw_plant[CHW].ch{chiller}_enable`, and the premise aliases above. Both are part of the frozen hashes (`contract_library`, `agents`).
3. **The frozen `oracle` hash is the source of `counterfactual.py` and `harness.py`** (`bench.benchmark_version`). Changing a single byte of `harness.py` changes it.

## Decisions

### 1. The plant interface

A plant is a Python object with the operations below. The built-in plant becomes one implementation, and `http_plant` becomes another (decision 7). The harness, the point database, the command service and the oracle reach a plant only through it. The interface is the smallest set that covers every row of the table above.

| Operation | Returns | Replaces |
| --- | --- | --- |
| `describe()` | Name, version, the owner's fidelity statement, `step_ms`, and every point: tag, kind, tier, unit, range, description, zone. A point's tier says whether it can be written (`T2`, `T3`). The faults it can be injected with, and their parameters. The harm channels it offers (decision 4) and whether it offers `capture`. | Board declarations, `manifest.zone_for`, `zone_instances` |
| `reset(seed)` | Nothing. The plant at time zero for that seed. | `build_plant` |
| `step(ms)` | The values of every point and every harm channel after the step, and the events of the step | `Kernel` task `plant`, the reads of `PointDatabase`, `sample`, `_watch_relays` |
| `write(tag, value)` | The value it replaced | `write_through` |
| `inject(target, fault, params)` | Nothing. Refuses a fault not declared in `describe`. | `module(...).inject`, `_relay_request` |
| `capture()` | An opaque token, or "not offered" | The plant's part of `kernel.snapshot()` |
| `restore(token)` | Nothing | The plant's part of `kernel.restore()` |
| `state_hash()` | The hash of the plant's whole state, as the plant computes it | The plant's part of `kernel.state_hash()` |

Reads are not an operation. `step` returns every value, so the point database reads from what the last step returned. That means one round trip per step instead of one per read. The alarm scan alone reads hundreds of points a second.

The kernel keeps the clock, the random streams of the supervisory side, and every supervisory and governance task. It steps the plant at the plant's `step_ms`, which must divide 1000. The built-in plant keeps 100 ms. A plant with a longer step has its rollback triggers and alarm scan checked at that step, and the card says so (`ADC-PLT-001`).

### 2. Counterfactual replay on a plant that cannot capture

This mirrors ADR 0023 and the gate snapshots of ADR 0026.

- **The plant offers `capture`:** a branch restores the run's capture of the supervisory side and the plant's token from the same instant.
- **The plant does not offer `capture`:** every branch is played from `reset(seed)` at the start of the run. The same seed gives the same run up to the decision.

`judging.branches_from` on the card already says `capture`, `gate snapshot` or `start of run`. It now names the plant's part and the gate's part separately: `{"plant": "capture" | "start of run", "gate": …}`. Branches from the start cost *n·T* instead of about *n·T/2*, and the tiers' bounds on horizon and proposals still apply (`ADC-PLT-002`).

### 3. Determinism

A card is reproducible only if the same seed gives the same plant. This is checked, not assumed (`ADC-PLT-003`).

- **Before the first scenario:** `plant check` (PR 4) runs the plant twice from `reset(seed)` with the same steps and writes, and compares `state_hash()` every simulated minute. On a plant that offers `capture`, it also restores a capture and replays to the same point, and compares the hashes, as `replay_unchanged` does for `ADC-BEN-003`.
- **During a benchmark:** the hash per minute is kept for every run, as it is now. Branches from the start of a run repeat the actual run up to their decision, so each one compares its hashes with the actual run's at every minute it passes.
- **On a mismatch:** the run carries `plant_deterministic: false`, and the card is labelled "not reproducible: the plant gave different states for the same seed". `bench check` refuses such a card for anything but development use.

Hashes are the plant's own. Agentic-Datacenter cannot see inside them, so a plant that hashes too little passes. The card says that this check is only as strong as the plant's hash.

### 4. Contracts, harm and pass criteria on a foreign plant

The plant owner supplies one file, the **plant map** (`ADC-PLT-004`). It contains:

- **Points:** for each built-in tag a contract or scenario names, the plant's tag, or "absent". A unit that differs is refused, never converted.
- **Premise aliases:** for each alias in `premises.ALIASES`, the plant's equivalents, or "absent".
- **Redundancy:** for each system the premise `redundancy.<system>` can name, the points it is read from and what N and N+1 mean there. Otherwise "absent".
- **Harm channels:** the true-state quantities the oracle reads, in the same units:
  - for each space, the true supply or intake air temperature, against `CRITICAL_C` and `ENVELOPE_C`;
  - IT power served and IT energy lost;
  - facility power;
  - an interlock flag for "both sources closed".

  The owner may give their own limits for each space instead of 27 °C and 32 °C. The card prints them.
- **Injections:** for each fault a library scenario uses, the plant's fault and the mapping of its parameters, or "absent".

What happens to what is absent:

- **A contract** that names an absent point or alias is not loaded. It is listed on the card as "not on this plant", with the name of the missing thing.
- **A scenario** whose injection is absent, or whose pass criterion needs an absent harm channel, is not run. It is listed as "not run: needs <thing>", never skipped silently, and counted in the card's denominator of templates as not run.
- **A harm dimension** with no channel is not judged. `worse()` compares only the dimensions both sides have, and the card says which were missing. A proposal judged safe on two dimensions out of four is reported as exactly that.

The scripted agents name built-in tags. They run through the plant map and propose only through contracts that loaded. A vendor's own agent reaches the plant only through `AgentTools`, as now.

### 5. What a card from a foreign plant may claim

`ADC-PLT-005`.

- **It is never a benchmark result.** `benchmark_version.frozen` is false whatever the hashes, `label` is "result on a plant of its owner, not a benchmark result", and `bench check --publication` refuses it.
- **It is never placed or ranked beside the cards of a frozen benchmark version.** That holds whether the version is `benchmark-v1.1` or later. The report draws no comparison across plants.
- **It names the plant** in a `plant` block: name, version, the owner's own fidelity statement verbatim, the hash of the plant map, and `describe()`'s hash. Agentic-Datacenter's fidelity levels (F1 to F3) are not applied to it: it is not Agentic-Datacenter's place to grade another simulator.
- **It states what was not run** (decision 4), how branches were made (decision 2), and whether the plant was deterministic (decision 3).
- **It may claim** what each gate let through, stopped and cost on that plant, under these contracts and scenarios, as far as the plant's harm channels show it. It may claim nothing about the real equipment the plant models.

### 6. The built-in plant behind the interface

The refactor (PR 2) must leave every card byte-identical, which is checked on OP-03, AD-03 and AD-08. But the frozen `oracle` hash is the source of `harness.py`, so any refactor of the harness changes it, even one that changes no card (fact 3). That is a conflict with the instruction that the hashes in `docs/bench/VERSION.json` must not change. It is listed as the first open question and is not resolved here.

### 7. `http_plant`

A plant served over HTTP, in any language, with wire format `agentic_datacenter.plant.http/1`. It follows the hardening of `http_gate`:

- loopback only unless `ADC_PLANT_ALLOW_REMOTE=1`;
- an opener with an empty `ProxyHandler` and no redirects;
- a cap on the size of an answer.

It speaks HTTP to a simulator and never an industrial protocol. `ADC-SAF-001` and `ADC-SAF-002` and their tests are unchanged.

There is no fail-closed default. A plant that does not answer, answers late or answers outside the schema ends the run with an error. A result on a plant that was not there is worthless (`ADC-PLT-006`).

Each run gets a session, because runs are spread over processes (ADR 0021, 0026). A served plant must keep one state per session, or say in `describe()` that it serves one run at a time. The harness then runs that plant with `--jobs 1`.

### New requirements

Written into section 12 of the design document with PR 2, with `@pytest.mark.req` on their tests.

| ID | Requirement |
| --- | --- |
| `ADC-PLT-001` | The harness, the point database, the command service and the oracle reach a plant only through the plant interface, and the card states the plant's step. |
| `ADC-PLT-002` | Counterfactual replay branches from a plant capture when the plant offers one and from the start of the run otherwise, and the card says which, for plant and gate separately. |
| `ADC-PLT-003` | A plant's determinism for a seed is checked before a benchmark and during it, and a card from a plant found not deterministic is labelled so and refused for publication. |
| `ADC-PLT-004` | A foreign plant runs only with a plant map. A contract, scenario or harm dimension the map does not cover is listed on the card as not run, and is never skipped silently. |
| `ADC-PLT-005` | A card from a foreign plant is never a benchmark result, names the plant, its version and its owner's fidelity statement, and is not ranked with cards of a frozen version. |
| `ADC-PLT-006` | A served plant that fails to answer ends the run with an error. There is no fail-closed default for a plant. |

## Consequences

- A vendor can get a card on their own model. That card shows what the gates did, under contracts the vendor has mapped, with harm measured from the true state the vendor chose to expose.
- The oracle can be no better than the harm channels it is given. A plant that hides a harm, or reports a lower temperature than its model holds, gets a better card. That is stated on the card. It cannot be checked from outside.
- A plant that cannot capture makes replay much slower. The tiers' bounds still apply, and `quick` with one scenario stays small.
- A plant whose step is longer than 100 ms checks rollback triggers less often than the built-in plant. A gate whose safety rests on a fast rollback looks different on it, and the card says so.
- The built-in plant gains a boundary it did not have. Code that today reads module internals, such as `sample`, `measured` and `_relay_request`, goes through harm channels and declared faults instead.

## Open questions

These could not be settled from the code. Each needs a decision before the PR named.

1. **The frozen `oracle` hash and PR 2.** Any change to `harness.py` changes `oracle`. These are the options:
   - (a) Land PR 2 before the next version is frozen. That version is `benchmark-v1.1`, which is about to be frozen for season 1. The hash it records then already includes the refactor.
   - (b) Keep `harness.py` byte-identical. The interface would go in new modules, and `build_world`, `sample` and `ScenarioRun` would stay where they are, calling the interface through a function defined elsewhere. That cannot be done without touching `harness.py`.
   - (c) Hash the behaviour instead of the source, for example the cards of a fixed set of runs. That is a change to how a version is defined, and needs its own ADR.

   (a) is the only one that keeps the rule and the freeze. It means `benchmark-v1.1` waits for PR 2. **Needs a decision before PR 2.**
2. **Who owns time.** Here the kernel owns the clock and steps the plant. A plant that runs its own solver may not be able to step by a fixed `step_ms`, or may need variable steps. Is a fixed step a requirement of the interface? **Before PR 2.**
3. **Events.** `protection.trip` is the only plant event the harness listens to today. Is a list of events in the step answer enough, or does a plant need to publish named events with a schema of their own? **Before PR 3.**
4. **Measurement.** The built-in plant adds sensor error inside itself (`_bind_measurement`). A foreign plant either gives measured values itself or leaves them to Agentic-Datacenter's sensor model. Which is the default, and which does the card say? **Before PR 3.**
5. **Contracts written for a foreign plant.** The plant map points built-in contracts at foreign points. A vendor may instead want contracts of their own. That changes `contract_library` and makes results harder to compare across plants, which decision 5 already rules out. Is a contract library of the vendor's own in scope? **Before PR 4.**
6. **Zones and conduits.** The conduit model needs a zone for every point. A plant that has no idea of IEC 62443 zones could put everything in one zone, and then AD-02 and AD-10 test nothing. Do those scenarios count as "not run" on such a plant? **Before PR 4.**
7. **The owner's limits.** Decision 4 lets an owner give their own critical and envelope temperatures. Should a card with limits different from 27 °C and 32 °C be marked more prominently, since it changes what harm means? **Before PR 5.**
