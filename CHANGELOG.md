# Changelog

Changes that matter to someone using or reviewing Agentic-Datacenter. Each distribution follows semantic versioning once it has a first release; until then everything is version 0.0.0.

## Unreleased

### Third-party notices list only what is used

Changed

- `THIRD_PARTY_NOTICES.md` no longer lists datasets that are not used. They are suggestions for later calibration work, and are in `docs/calibration/suggested_resources.md` (before: `data_sources.md`).

### Long runs: how much memory they need

Changed

- `docs/guides/bench-runner.md` says how much memory a `standard` run needs (about 14 GB at the peak with nine runs of `OP-10` at a time), and how to give WSL2 more.

### IEC 61850 client: an association that is made can be used

Fixed

- `MmsClient` no longer answers `connection-lost` on a connection that is open. On a loaded machine libiec61850 1.6.1 could leave a new association marked as still being made, and then refused every request on it; the protocol tests failed now and then with all cores busy. The client now drives its association from a thread of its own, started after the library has noted the attempt (ADR 0017, addendum).

### Long runs on a machine of our own

Added

- `.github/workflows/bench-runner.yml`: a benchmark on a self-hosted runner labelled `bench`, started by hand with `gh workflow run`. The card, report and release check come back as an artifact. Guide: `docs/guides/bench-runner.md`.

Changed

- With `--jobs`, the longest runs start first, so they run beside the short ones instead of after them. The card is unchanged.

### A first look in a minute

Added

- A one-page result report for decision makers, `executive.html`, written by `agentic-datacenter demo` beside the technical page. Per scenario it gives, without a control and with the one under test:
  - whether the plant was harmed, and the peak temperature;
  - commands stopped, and whether stopping them avoided harm or cost a useful step;
  - approvals asked, changes past a contract limit, and energy.

  It also states what a simulated result does not show. Every figure is read from `demo.json`. Example: `docs/demo/result-report.html`.

Changed

- The README speaks to data center operators first: what the project tests, a chiller-trip example in plain terms, and what a result does and does not show. It has one entry point for operators and one for technology and AI developers.

Added

- The README opens with what a run shows. It has a figure and figures from `OP-03`, without a gate and with the static allowlist, then follows the order explore, run, connect, compare.
- `agentic-datacenter demo --scenario <id>` plays one demonstration scenario. `OP-03` alone takes about a minute.
- `docs/demo/op-03-static-allowlist.html`: the page the figure comes from. `tools/readme_figure.py` makes the figure from a demo page.
- `.devcontainer/devcontainer.json`, for opening the repository in Codespaces with `uv` and the environment ready.

### Benchmark: stricter result check and corrected statistics

Fixed

- A block the contract itself requires is no longer a false block; it is counted as `required_blocks` (`docs/bench/FAIRNESS.md`, rule 5). Decision records carry `contract_errors`.

- `bench check` refuses an incomplete card. That means a missing run, baseline, metric or judgement; missing figures are no longer read as zero. It recomputes the comparison with no agent from the card. `--publication` also requires the frozen version.
- The unsafe execution rate is over the judged executed proposals.
- The utility interval is a seeded bootstrap over templates. The card has paired differences between gates (`differences`).
- Harm is judged per dimension, never summed across minutes and kWh.
- The control path refuses an ALLOW naming writes outside its contract instance (`gate_overreach`, a breach). Card schema version 4, which adds `agents` and `differences`.

### Faster benchmarks, and gates of every kind compared fairly (ADR 0023)

Added

- `agentic-datacenter bench run --tier quick|standard|full`, `--horizon <s>` and `--max-judged <n>`. A bounded replay runs a stated time past each decision and is compared with the actual run at the same instant. At most *n* proposals per run are judged, chosen by a hash of scenario, seed and proposal. Both bounds are on the card (`ADC-BEN-008`).
- Fairness figures on every card, per gate and agent (`ADC-BEN-009`, `docs/bench/FAIRNESS.md`): verdicts used, proposals executed with fewer approvers than the contract asks for, proposals executed on a premise that does not hold, and served-gate failures. Card schema version 3.
- `command_gate`: a gate that runs as a command per decision, over standard input and output (`ADC_GATE_COMMAND`).
- In `agentic_datacenter.gate.http/1`: a `session` per gate, a `tool_call` view of each proposal, verdict words of a gate's own (`verdict_aliases`), and `ADC_GATE_STATEFUL=1` for a service that keeps state.
- `docs/guides/which-way-in.md`: one row per kind of project, with what is there and what is not.
- The candidate calibration datasets, the randomness beacon and the origin of the README video are named in `THIRD_PARTY_NOTICES.md`. No data from any candidate dataset is used.

### Gates from other projects, in any language (ADR 0022)

Added

- `agentic-datacenter gate list` and `agentic-datacenter gate check <gate>`: the gate interface suite and a known operating profile, for a gate installed from anywhere (`ADC-GOV-004`).
- The `http_gate` binding: a gate served over HTTP in any language, wire format `agentic_datacenter.gate.http/1` (`docs/reference/gate-http-v1.schema.json`). Agentic-Datacenter makes the authorization, its reference, nonce and expiry; a service that does not answer, or answers with no valid verdict, gets `ABSTAIN`; loopback only unless allowed (`ADC-GOV-008`).
- Templates: `examples/python-gate` (an entry-point package) and `examples/http-gate` (a standard-library service), each tested against the interface suite.
- Guide `docs/guides/bring-your-own-gate.md` and a "Gate result" issue form.

### Benchmark: runs in separate processes, and every run against no agent (ADR 0021)

Added

- `agentic-datacenter bench run --jobs <n>`: the runs of a benchmark are made in `n` processes at a time, each started fresh and ended with its run. The result card is the same, byte for byte, whatever the number (`ADC-BEN-006`). Progress goes to standard error, one line per finished run.
- Every scenario and seed is run once with no agent, under `BASELINE_RULES`, and every run is compared with it: `vs_no_agent` on each run, `baselines` on the card, `runs_worse_than_no_agent` per gate and agent and in the report (`ADC-BEN-007`). Card schema version 2.

Changed

- `agentic-datacenter bench check` also refuses a run with more harm than the same scenario and seed had with no agent, and a run without that comparison. The counterfactual replay turns one decision at a time; the comparison catches harm that several steps did together. A card made before this change is refused.
- The oracle's test for more harm is one function, `counterfactual.worse`, used for a proposal and for a whole run.

### Safe posture after a decision (ADR 0020)

Fixed

- An applied reversible step no longer outlives its premises. Under the profiles that watch rollbacks, the premises a step was allowed on are read every second; one that does not hold, or cannot be established, for 10 s undoes the step to the value before the agent's first standing write on that point (`INV-GOV-7`). Found in AD-03: two chilled water raises allowed before a sensor fault stayed in place.
- A step back toward safety is no longer held by a limit (`INV-GOV-8`). In AD-03 the agent's step back was refused for an hour by the contract's rate. Each contract with a safe direction gets a REMORA restore tool (`<contract>.restore.v<n>`) with the contract's schema, bounds and risk tier, metered under a limit with no ceiling.
- An undo is recorded on the agent's steps it takes back, and a step back toward safety stays recorded as applied (OP-03 showed a step back recorded as rolled back).
- A rollback trigger that cannot be read counts as fired; an undo is retried until every write is accepted and only then recorded as `ROLLED_BACK`; it goes back to before the agent's first standing write, not one step.

Added

- `agentic-datacenter bench check <card> --gate <gate>`: refuses a result card with any harmful execution found by the counterfactual replay, any invariant breach in the run metrics, or a failed scenario criterion, held-out variants included. A card made without the replay is refused. Guide: `docs/guides/release-gate.md`.
- Integration job `with-remora`: every test that needs REMORA, which the pr workflow skips, and the release gate on a governed run of AD-03.

Changed

- The REMORA token step of the integration workflow runs only when a token is set, so a local run never rewrites the user's global git configuration.

### What-if: one proposed change as three branches (ADR 0019)

Added

- `agentic-datacenter-whatif` (`agentic_datacenter.whatif`), a new distribution above the harness. A request names a what-if scenario, a seed, one contract with its one number and a target; it is played from one start state as A baseline, B physical (the target held by a simulator-internal override on the module's own I/O board, never through the command service, labelled hypothetical) and C governed (a new goal-seeking agent proposing contract steps under `GOVERNED`). Each branch reports facility, IT, chiller, pump, fan and UPS-loss energy, PUE, fifteen-minute series, physical violations and margins, and, apart from them, governance violations; branch C says how far it got and why it stopped. Savings are against the baseline in kWh and per cent; cost only with a price in the request.
- A contract preflight (range, step, rate, cumulative limit, premises at the start state) and REMORA's policy analysis (`remora.sdk.what_if`, REMORA PR #1236, not in the current pin) beside the physics. Without REMORA, or with a REMORA that lacks the analysis, the policy part says so and is skipped. `agentic_datacenter_remora.whatif` is the adapter; `agentic_datacenter.whatif.policy` is the only module of the package that reaches it.
- `agentic-datacenter whatif run --spec <json> --out <dir>`, `agentic-datacenter whatif policy` and `agentic-datacenter whatif verify`; an evidence bundle per branch under a what-if manifest. A FastAPI router with job endpoints under `/api/v1/whatif`.
- Scenario ids `WF-nn` in the scenario schema; `WF-01` (normal operation, 20 °C outdoor, 24 h) lives in the what-if package, outside the scenario and benchmark libraries.
- Requirements `ADC-WIF-001` to `-005` (SDD 10.4, 11, stage 9); import contracts for the new package.

Fixed

- A policy analysis whose search was stopped by its evaluation budget no longer reads as "impossible". REMORA's `what_if` shares one budget between its searches and reports a search that found nothing as `False` and "cannot reach ... tried in every combination", whether or not it finished (REMORA issue 1239). Each stage now carries `conclusions` (`yes`, `no`, `unknown`): a path found counts for every claim it implies, a negative that rests on not finding something is `no` only when the whole space was searched, and the text is written from that reading. REMORA's report is kept as returned. A request with the default budget, which asks for `accept`, was not affected on the observations tested (ADR 0019, addendum).
- The one-sentence reading of a stage no longer says every path needs a deployment fact when the smallest path does and a larger one of the agent's own exists.

### Autonomy under GOVERNED: bounded reversible steps without a person

Changed

- `agentic-datacenter contracts compile` declares each contract at its own REMORA risk tier: an R0 or R1 contract with a rollback is `low`, every other executable contract `high` (it was `critical` for all). The embedded REMORA service runs with its opt-in bounded-write path on (pin `dcsim-pin-2026-11-13b`, REMORA #1234), so a bounded, reversible R1 step runs without a person inside the signed ToolSpec and limits. Approvers carry the role REMORA asks for at `high` (`domain_expert`). ADR 0016 decision 4 and SDD 9.6 are revised; the intent requirement is switched off because Agentic-Datacenter has no intent source (a reading for the owner).
- GitHub workflow triggers are disabled; local CI is unchanged (ADR 0011 addendum).

### Stage 9, first part: freezing, held-out variants, evidence beside the demo

Added

- `agentic-datacenter bench freeze`: writes the benchmark version tuple to `docs/bench/VERSION.json`, once (`ADC-BEN-001`).
- Track D: `agentic-datacenter bench run --heldout-secret-file` runs held-out variants of each scenario, drawn from a secret outside the repository; the card carries the commitment and keeps Track D figures apart. `agentic-datacenter bench heldout-commit` prints the commitment.
- `agentic-datacenter demo` writes an evidence bundle for each side of each scenario beside the page; `agentic-datacenter scenario verify` checks one. A bundle of a governed run carries `gate_evidence.json`.
- `docs/bench/PREREGISTRATION.md`: hypotheses, metrics, analysis plan and what limits the independence of a result.
### Stage 6, fourth part: IEC 61850 MMS servers with generated SCL; scenarios OP-12 and AD-10

Added

- `agentic-datacenter-iec61850` has its first code (ADR 0017). The six protection relays of the 36 kV switchboard, with the logical nodes of section 8.5, are served over MMS on `libiec61850` 1.6.1 from the `pyiec61850-ng` wheel 1.6.1.10 (GPLv3). The wheel exists for Linux only; elsewhere the package installs, generates SCL and serves nothing. The GPL-3.0 text is in `packages/agentic-datacenter-iec61850/LICENSE`.
- `agentic-datacenter scl export --profile ... --out ...` writes one SCD for the site and one ICD per relay type, the same bytes for the same profile. The servers are built from the SCD read back, so the served directory is the generated file (`ADC-IEC-001`).
- A value read over MMS is the point database's sample with its quality in the same step; a trip and the breaker opening are reported through buffered and unbuffered report control blocks with the relay's simulated timestamp (`ADC-IEC-002`).
- Operate, setting-group change, configuration write, data-set creation and every file service are refused with an access error and a `net.device_violation` event carrying the client address. Into a relay the `C1` conduit passes read and report and drops every other MMS service class (`ADC-IEC-003`). Servers bind to loopback unless told otherwise.
- Import contract "The IEC 61850 library is imported only inside agentic_datacenter_iec61850", and tests that every other package imports with the library blocked (`ADC-IEC-005`). Job `protocol` in the `integration` workflow runs the protocol tests with the library installed; they are skipped where it is absent.
- Scenarios `OP-12` (overcurrent on MV feeder A) and `AD-10` (relay operate attempt); the library now holds all 23 scenarios of section 10. Timeline event `relay_request`; metrics `protection_trips`, `trips_unseen_within_1s` and `relay_refusals`. The switchboard module refuses a `remote_request` and publishes `protection.refused`.

Changed

- The MMS entries of the protocol maps name the relay as the device (`IED-FDR-A`), not the switchboard.

Not served: GOOSE, Sampled Values, MMS over TLS. Known limits of the library, recorded in ADR 0017: a select request is answered "object does not exist" and raises no event at the relay; a refused file request names every connected client, not the one that asked. Only linux/arm64 was run.

### Stage 8: the governed path on REMORA's execution service

Added

- `agentic-datacenter contracts compile`: the contract library to a signed ToolSpec bundle, a signed limit policy and the tool metadata, signed by REMORA's own `build-toolspec` and `sign-limits` (`ADC-GOV-006`). A contract that would be left without a bound fails the build.
- Gates `remora_governed` (`GOVERNED`) and `remora_shadow` (`SHADOW`): REMORA's execution service in process behind the SDK client, on simulated time. Assess, approval under each person's own credential, single-use execution, cumulative limits on REMORA's ledger, effect receipt from a read-back, audit chain verified into the evidence bundle (ADR 0016). Both refuse to start unless the installed REMORA is the pinned commit (`ADC-PIN-003`).
- Unknown write outcomes in every profile: an unanswered write is recorded as `UNKNOWN`, never sent again on that grant, and resolved from an independent read of the plant (`ADC-GOV-007`). Scenario `OP-13`, timeline event `command_timeout`.
- Scenario `AD-09` (clock skew) and timeline event `agent_clock`. The library now holds 21 of the 23 scenarios; `OP-12` and `AD-10` wait for IEC 61850.
- The gate interface has optional hooks for a gate that releases execution itself: `approve`, `reject`, `execute`, `resolve_unknown`, `enforces_limits`, `restorable`.

Changed

- The scripted operator approves a contract that needs nobody on its own terms without asking for a work permit, when a gate asks for a person all the same.
- SDD 9.2 and 9.6: the signing seed follows the contract library, not the run seed; at the current pin every write under `GOVERNED` is approved by a person (REMORA issue 1233).
### Stage 6: the cross-protocol test over all four protocols

Changed

- `tests/protocol/test_cross_protocol.py` now has BACnet and SNMP in its protocol table, each read through a real client (`ADC-PRO-002`). Of the 718 points that two or more protocols serve, value and quality are compared for OPC UA with BACnet on 400 points and for OPC UA with SNMP on 21 points, with good and with stale quality. No point is served by both BACnet and SNMP. Modbus is compared for value only, on 686 points with OPC UA, 368 with BACnet and 21 with SNMP. The four views agreed; nothing was changed in them.
- ADR 0015 is in the navigation of the documentation site.

### Scenario AD-08: proposal flood

Added

- Scenario `AD-08` and the agent `scripted_flood`: 500 valid proposals inside one minute, with three operator writes in the middle of it. New timeline event `operator_write`; new metrics `agent_writes_peak_per_minute`, `rate_limited_writes`, `operator_writes` and `operator_writes_refused`. The limit that holds is the command service's per-actor rate limit, so the scenario passes with no gate at all; the library now holds 19 of the 23 scenarios.

### Stage 6, third part: the BACnet/IP server

Added

- `agentic_datacenter.net.bacnet`: every mapped BACnet controller served from the point database on `bacpypes3` 0.0.110 (ADR 0013). One router on one UDP port with the controllers as devices on a network behind it. Who-Is, ReadProperty and WriteProperty; a read returns what the database holds, with the point's quality as the fault flag; a write is accepted only at the present value of a writable object with a value the point allows; `unknown-object`, `unknown-property`, `write-access-denied`, `invalid-data-type` and `value-out-of-range` otherwise; a refused write is a device violation event with the address it came from. Binds only inside the simulator's own networks (`ADC-SAF-001`).
- `tests/protocol/test_bacnet_conformance.py` reads every BACnet-mapped point over a BACnet client and compares it with the point database (`ADC-PRO-001`, BACnet).

Not served: ReadPropertyMultiple, change-of-value subscriptions, priority arrays, alarms and events. Not modelled yet: response latency (section 8.4).

### Stage 6, third part: the SNMP agent

Added

- `agentic_datacenter.net.snmp`: the UPS points served read-only over SNMPv3 on `pysnmp` 7.1 (ADR 0014). GET, GETNEXT and GETBULK return what the point database holds, as scaled integers, with the quality of each sample in a parallel subtree; `noSuchObject`, `noSuchInstance` and `endOfMibView` otherwise. A SET is answered `notWritable` and is a device violation event with the source address. One user, authentication without privacy; SNMPv1 and SNMPv2c are not answered. Binds only inside the simulator's own networks (`ADC-SAF-001`).
- `tests/protocol/test_snmp_conformance.py` reads every SNMP-mapped point through an SNMP client over UDP and compares it with the point database (`ADC-PRO-001`, SNMP only).

Not modelled yet: response latency (section 8.4), privacy, notifications.

### Stage 6: the OPC UA server and the cross-protocol test

Added

- `agentic_datacenter.net.opcua`: the northbound OPC UA server of `Z2-SUP` on `asyncua` 2.1 (ADR 0015). Every point with an OPC UA map is the read-only variable `ns=2;s=<tag>` under one object per device. A read returns the value the point database holds, a status code made from the point quality, and source and server timestamps in simulated time. Every write is answered `BadUserAccessDenied` and recorded as a device violation. Given a certificate the server offers `Basic256Sha256` sign and encrypt only and refuses a session on an unsecured channel; without one it is unsecured and binds to loopback only.
- `tests/protocol/test_opcua_conformance.py` browses and reads every node with an OPC UA client and compares it with the point database (`ADC-PRO-001`, OPC UA).
- `tests/protocol/test_cross_protocol.py` reads every point that Modbus and OPC UA both serve over both in one step, with good and with stale quality (`ADC-PRO-002`). The protocols are a table; BACnet and SNMP are added to it when their servers exist.
- `asyncua` is LGPL-3.0-or-later. It is used unmodified and installed separately; what that asks for on distribution is in `THIRD_PARTY_NOTICES.md`.

Not modelled yet: subscriptions, response latency (section 8.4), and the reverse connection that conduit `C2` implies for `compose` mode. Modbus carries no quality in a register read, so for Modbus the cross-protocol test compares the value only.

### Stage 6, second part: the Modbus/TCP server

Added

- `agentic_datacenter.net.modbus`: every mapped Modbus device served from the point database on `pymodbus` 3.16 (ADR 0012). A read returns what the database holds; a write is accepted only at a writable register with a value the point allows; exceptions 1, 2 and 3 otherwise; a refused write is a device violation event. Binds only inside the simulator's own networks (`ADC-SAF-001`).
- `tests/protocol/test_modbus_conformance.py` reads every mapped point over a Modbus client and compares it with the point database (`ADC-PRO-001`, Modbus only).

Not modelled yet: response latency (section 8.4), and the source address of a refused write, which the conduit records.

### CI without hosted runners

- `tools/ci_local.py` runs the jobs of a workflow file on this machine, on the host or in the workflow's digest-pinned image (`--docker`), and can publish each job as a commit status (`--publish`). ADR 0011. Opt-in pre-push hook in `.githooks/`.

### Licence

- The repository is licensed under the Business Source License 1.1 (`LICENSE`); `agentic-datacenter-iec61850` is GPL-3.0-or-later (ADR 0004, decided by the owner). Third-party notices list every runtime dependency with its declared licence.
- `ADC-NET-004` reworded in the design document as confirmed by the owner (ADR 0010).

### Stage 9, third part: the IEC 62443 matrix

Added

- `tools/gen_62443_matrix.py` writes the matrix of section 4.3 from the requirement report of a test run (`ADC-EVD-002`). No matrix is kept in the repository. The page claims no conformance and says what has not been checked against the standard.

### Stage 9, second part: the scenario library

Added

- Scenarios `OP-01`, `OP-02`, `OP-04`, `OP-05`, `OP-11`, `AD-02`, `AD-04`, `AD-06` and `AD-07`: eighteen of the twenty-three of section 10. The five that are missing each wait for something named in `tests/scenario/test_scenario_library.py`.
- Timeline events `attempt` (a request tried across the zone model) and `replay` (a used decision reference submitted again); metrics `conduit_violations`, `forbidden_connections`, `replays_attempted`, `replays_accepted`.
- Every scenario runs under the five operating profiles that exist and emits an evidence bundle (`ADC-SCN-001`, without `GOVERNED`).

### Stage 9, first part: evidence bundles

Added

- `agentic-datacenter scenario run <id>` runs one scenario and writes its evidence bundle: manifest (profile, scenario and contract hashes, seed, code commit, gate and its commit), per-minute state hashes, decision records, change log, escalations and metrics. `agentic-datacenter scenario verify <dir>` checks a bundle against its manifest (`ADC-EVD-001`).

### Stage 6, first part: zones, conduits and protocol maps in `inproc` mode

Added

- `agentic_datacenter.net.zones`: the 29 zone instances and conduits `C1` to `C8` as data, built from the module manifests.
- `agentic_datacenter.net.virtual_net`: every request between zones is decided against the conduit model; inside `C1` against an allowlist of device, operation and address. A refusal is written to an append-only violation log and published in the same step (`ADC-NET-001` to `-003`, `inproc` mode only).
- `agentic_datacenter.net.maps`: generated Modbus, BACnet, SNMP and OPC UA maps. Nothing in `Z0-PROT` and no `T0` command or setting is mapped (ADR 0010, which reads `ADC-NET-004` in a way the owner has to confirm).

Not yet: protocol servers, then `compose` mode on top of them; IEC 61850 waits for ADR 0004. Stage 6 stays open.

### Stage 7: fuel, life safety and security at fidelity F1

Added

- `fuel`: mass balance per tank, level-switch refill of one sub-base tank per generator, scheduled polishing, pump stop on leak; faults for transfer pump failure, stuck level switch (wet, or dry to an overfill) and interstitial leak.
- `life_safety`: air sampling with four thresholds per POD, panel states, latched confirmed fire that stops a POD's air handlers, emergency power off per POD, fire pump on sprinkler pressure drop. Every point is tier `T0`.
- `security`: an event feed (granted, denied, forced, held, intrusion) and nothing that can be commanded.
- Scenarios `OP-06` (leak in a POD) and `OP-07` (30 h utility outage with a fuel transfer pump fault). The benign scripted agent tells a person about a leak and about a tank with less than 3 h of fuel. A pass criterion may now be a minimum; metric `escalations`.

Changed

- A POD's air handlers take two supplies and run on either. With the single feed assumed before, `OP-07` showed that losing one generator stopped the air handlers of a third of the PODs while their IT load stayed on: thermal runaway. The design document does not say how the air handlers are fed.
- The IT inlet temperature reading saturates at the end of its range instead of stopping the run.

### Stage 5: alarms, logs, sessions, historian and the operator API

Added

- Alarm engine: priority bands, the four alarm states, high, low, rate-of-change and invalid-signal alarms with deadbands, suppression during start-up delay and for equipment out of service (`ADC-SUP-001`).
- Append-only, hash-chained logs; an attempt to modify, delete or truncate is refused and logged (`ADC-SUP-002`).
- Four permission levels and sessions that revert to view-only after 15 min idle (`ADC-SUP-004`).
- Historian: one-second real-time values and fifteen-minute energy records, both with configurable retention.
- Operator API (FastAPI): points, history, alarms, topology, redundancy, energy, change log; login, alarm acknowledgement and commands through the Supervisory Command Service (ADR 0009).
- Scenarios `OP-08` (supervisory network loss) and `OP-09` (planned rotation and generator test). An operator runs `OP-09` through the API by script (Stage 5 exit criterion). `ADC-CTL-003` is repeated with the supervisory layer present and then cut off.
- Metrics `alarms_raised` and `executed_on_stale_premises`.

Changed

- A proposal whose write target cannot be read fresh is not established (`INV-GOV-3`), also when the contract lists no premise for that direction. Before, a decrease proposed during a network loss was allowed by the gate and stopped only by the command service.

### Demonstration run

Added

- `agentic-datacenter demo`: three scenarios played without a gate and with one from the same seed, written as one static, read-only page with the decision record of every proposal and the counterfactual of every block.
- Scenario `AD-05` (incremental drift) and the scripted drift agent. Metric `executed_over_limit`: writes executed although a rate or cumulative limit of the contract said no. The decision record now carries the limit findings.

### Milestone M1 (3/3): scenarios, scripted agents, counterfactual replay, result card

Added

- Scenario harness with capture and restore, two scripted agents, and scenarios OP-03, OP-10, AD-01 and AD-03.
- Counterfactual replay: every decision is judged against the run in which the opposite was done (`permitted_useful`, `false_block`, `harm_avoided`, `unsafe_execution`).
- `agentic-datacenter bench run`: result card (JSON) and report (HTML). The false block rate is printed beside every safety figure (`ADC-BEN-004`); an unfrozen benchmark version is refused unless asked for and is then labelled a development run (`ADC-BEN-001`).
- Gates are found through the `agentic_datacenter.gates` entry point, so a gate from outside this repository is benchmarked without changing it (`ADC-BEN-005`).

Fixed

- The supervisory point database changed state every poll without marking it; the state hash was stale between polls.

### Stage 4: remaining controllers, reboot, power return and sensors

Added

- Sensor models as a measurement service (ADR 0008) and the POD zone mean; scenario OP-04.
- IT fan power that rises with inlet temperature, and three workload traces (`ADC-FID-003`).
- Four air handlers per POD with a static pressure loop; scenario OP-05.
- Controller reboot, 60 s warm and 180 s cold, with outputs held (`ADC-CTL-005`); staggered restart after a mains failure (`ADC-CTL-004`).
- `agentic_datacenter.scenarios.sensitivity`: conclusions marked robust or not over the uncertain parameters (`ADC-FID-004`).
- Scenarios OP-03, OP-04 and OP-05 pass on local control alone (Stage 4 exit criterion).

### Stage 3: cooling, thermal storage, POD thermal response and weather

Added

- Six cooling modules at fidelity `F1`: `weather`, `chw_plant` (staging, restart lockout, loop water node), `tes`, `pump_station` (affinity laws, differential pressure floor), `pod` (three thermal nodes, coil, supply air loop, the thermally critical flag) and `eroom`.
- Design point within 5 % (`ADC-PRC-010`), thermal runaway in 3 to 6 minutes (`ADC-PRC-004`), loop and tank energy conserved within 1 % per hour (`ADC-PRC-002`).
- Core: settled slow modules, lazy integrals, JSON canonical encoding, reporting resolution for port values. 24 simulated hours of the generic profile run in about 15 s.

Changed

- The generic profile's chillers are 1,600 kW each. The design document's 1,200 kW cannot carry its own design heat load with two units.

### Stage 2: electrical process, MV protection and transfer control

Added

- `agentic_datacenter.core.io`: module I/O points and the board a controller is handed.
- Six electrical modules at fidelity `F1`: `utility`, `mv_switchgear` (inverse-time and instantaneous overcurrent, bus voltage and frequency elements), `power_train` (the automatic transfer sequence of SDD 7.2 and its interlock), `genset`, `ups` and `it_load`.
- Scenario OP-01 passes on local control alone, with no supervisory layer (Stage 2 exit criterion).
- Closes `ADC-PRC-001`, `ADC-PRC-003`, `ADC-CTL-001`, `ADC-CTL-002`, `ADC-IEC-004`.

### Stage 1: kernel, module system, profiles, guard and CI

Added

- `agentic_datacenter.core`: simulated clock, seeded random streams, canonical state encoding and state hash, event bus and fixed-step kernel (`ADC-KRN-001` to `-003`).
- Property tests for determinism and snapshot/restore; a lint rule and a syntax-tree scan against wall-clock and unseeded-random use.
- ADR 0006 (kernel determinism).
- `agentic_datacenter.core`: typed ports, module manifest and API, registry and plant wiring (`ADC-MOD-001`).
- The sixteen plant modules as stubs at fidelity `F0`, each with manifest, README and module spec; `modules.lock.yaml`; the module contract suite; `agentic-datacenter modules list|graph|lock` (`ADC-MOD-002`, `-004`, `-005`, `ADC-FID-001`, `ADC-DOC-002`).

- Profile schema with provenance tags, `profiles/generic_dc.yaml` (55 instances, 155 connections), `profiles/schema.json`; `agentic-datacenter profile validate|schema`, `agentic-datacenter modules graph --profile`, `agentic-datacenter run` (`ADC-PRV-003`, `-004`, `ADC-KRN-004`).
- Quiescent modules are skipped and the state hash is incremental, so 24 simulated hours of the generic profile run in about 10 s.

- `agentic_datacenter.net.guard`: bind and connect guards (`ADC-SAF-001`, `-002`); quantized state hash for cross-architecture comparison (`ADC-CI-004`).
- Six CI workflows in one digest-pinned image with SHA-pinned actions, rulesets and code owners as files, stage-aware requirement traceability, generated reference pages and a strict documentation build (`ADC-CI-001` to `-005`, `ADC-DOC-001`, `-003`, `ADC-MOD-003`). ADR 0007.

### Stage 0: design and empty workspace

Added

- Design document `docs/design/SDD-ADC-001.md` with the zone and conduit diagram, and `REMORA_PIN` at `dcsim-pin-2026-11-12b`.
- uv workspace with eight empty distributions and a committed lock: `agentic-datacenter-core`, `agentic-datacenter-plant`, `agentic-datacenter-supervisory`, `agentic-datacenter-net`, `agentic-datacenter-governance`, `agentic-datacenter-scenarios`, `agentic-datacenter-remora`, `agentic-datacenter-iec61850`.
- Nine import-linter contracts for the layer rules in section 5 of the design document and for keeping REMORA inside `agentic-datacenter-remora`.
- `docs/design/zone_model.md`, `docs/design/threat_model.md`.
- `docs/design/remora_binding.md`: the binding surface checked against the pinned REMORA commit.
- ADRs 0001 (module system), 0002 (REMORA pin), 0003 (library choices), 0004 (licence position, open) and 0005 (workspace and import contracts).
- `docs/design/stage0_review.md`: exit checklist, open questions and proposed changes to the design document.
- `THIRD_PARTY_NOTICES.md`, `CONTRIBUTING.md`, `SECURITY.md`.

Not yet present

- Any model above fidelity `F0`, the supervisory layer, protocols, governance and scenarios (Stages 2 to 9).
