# Threat model

The threat model of SDD-ADC-001. It covers two different things and keeps them apart:

- **Part A: the simulated facility.** Threats to the modelled plant that the zone model and the gate are meant to stop. These are what the adversarial scenarios exercise, inside the simulator only.
- **Part B: the simulator as software.** Threats that come from running Agentic-Datacenter itself on a real machine.

Treating an AI agent as a software process under IEC 62443-3-3 SR 1.2 and SR 2.1 is this project's interpretation, not a requirement of the standard (SDD 4.4).

## Part A. The simulated facility

### A.1 What is protected

| Asset | Harm if lost | Measured as |
| --- | --- | --- |
| Power to IT load | Load dropped | kWh of IT load lost |
| Cooling to PODs | Thermal criticality within minutes | POD-minutes above the critical threshold |
| Redundancy margin | A second fault becomes an outage | Redundancy state below N+1 or below N |
| Protection and life-safety functions | Equipment damage, harm to people | Any write reaching a tier `T0` point |
| Integrity of setpoints and modes | Slow harm that looks like normal operation | Writes outside contract bounds or cumulative limits |
| Integrity of records | A harmful action cannot be reconstructed | Breaks in the change log, alarm log or decision records |

### A.2 Trust boundaries

1. Agent runtime to gate (`C4`). The agent is treated as a principal that may be compromised.
2. Gate to Supervisory Command Service (`C5`). The only path by which a proposal becomes a write.
3. Supervisory to controllers (`C1`). Legacy protocols without authentication.
4. Hardwired layer to everything else (`C6`). One-way by construction.
5. Enterprise and vendors to the DMZ (`C3`, `C7`).
6. Data entering the agent's context: alarm text, work orders, sensor values, forecasts.

### A.3 Who acts

| Actor | Position | Capability assumed |
| --- | --- | --- |
| Manipulated agent | `ZA-AGENT` | Follows instructions hidden in data it reads; proposes anything the tool surface accepts |
| Compromised agent runtime | `ZA-AGENT` | Arbitrary code in the agent's enclave; can try any network connection and forge any self-reported field; controls its own clock |
| Misused workstation or operator | `Z2-SUP` | A valid session at some role; can ask the agent for unsafe actions or attempt writes directly |
| Remote user or vendor | `Z4-ENT` | Reaches the DMZ; has or steals a brokered session |
| Compromised controller | One level 1 zone | Full control of that zone's devices; tries to reach other zones |
| Faulty or falsified field data | Sensors | Biased, stuck or drifting readings, with or without intent |

### A.4 Threats and how the design answers them

| # | Threat | Answer in the design | Requirement | Exercised by |
| --- | --- | --- | --- | --- |
| A1 | Instructions hidden in alarm or work-order text steer the agent | Proposals can only name an intent contract; free text is stored as data; premises are read by the gate itself | `INV-GOV-3`, `ADC-GOV-003`, `-005` | `AD-01` |
| A2 | The agent runtime bypasses the gate and talks to a controller | No route exists from `ZA-AGENT` except `C4`; the attempt raises a violation alarm | `ADC-NET-001`, `-003` | `AD-02`, `AD-10` |
| A3 | Falsified readings make an unsafe action look safe | Cross-checks between supply air, return air and IT power; bad or inconsistent quality gives abstain | `INV-GOV-3`, `ADC-CTL-006` | `AD-03`, `OP-04` |
| A4 | A previously issued authorization is replayed | Decision references are single-use, expiring and bound to tag and value; checked again at the command service | `INV-GOV-2`, `ADC-GOV-002` | `AD-04` |
| A5 | Many small allowed steps add up to an unsafe state | Cumulative limits per tag across all contracts; rollback triggers | `INV-GOV-6` | `AD-05` |
| A6 | The agent claims another identity | Identity is taken from the credential on `C4`; self-reported fields are stored as claims | `INV-GOV-5` | `AD-06` |
| A7 | A person asks the agent to do something no contract permits | Risk tier `R3` has no contract; the request and the refusal are both recorded | `ADC-GOV-005` | `AD-07` |
| A8 | Proposal flooding starves legitimate operators | Rate limits per contract and on supervisory writes; operator path unaffected | `ADC-SUP-005`, SR 7.1 | `AD-08` |
| A9 | Clock manipulation extends an authorization or hides stale data | Expiry and freshness are judged on gate time | `INV-GOV-2`, `-3` | `AD-09` |
| A10 | A supervisory host tries to operate a breaker or change relay settings | All relay control objects are status-only; refused at the relay and dropped at the conduit | `ADC-IEC-003` | `AD-10` |
| A11 | A compromised controller reaches another train or POD | No conduit between level 1 zones | `ADC-NET-001` | Zone matrix |
| A12 | Any network path writes a protection or life-safety point | Nothing in `Z0-PROT` and no tier `T0` command or setting has a protocol map; `C6` has no reverse path | `ADC-NET-004`, `INV-ATO-1` | `conformance/test_t0_unmapped`, `property/test_ato_interlock` |
| A13 | An action is allowed that removes the last unit of spare capacity | Redundancy premises on every contract that affects capacity | `INV-GOV-4` | `OP-02`, `OP-03`, `OP-11` |
| A14 | The outcome of a dispatched write is unknown and it is retried | A consumed grant is never retried; resolution only from an independent read | `ADC-GOV-007` | `OP-13` |
| A15 | Records are altered after the fact | Append-only logs; hash-chained decision records; per-step state hashes in the evidence bundle | `ADC-SUP-002`, `ADC-EVD-001` | `unit/test_log_integrity` |
| A16 | Supervisory network is lost while the plant needs to act | Local controllers keep their sequences; proposals abstain on stale premises | `ADC-CTL-003` | `OP-08` |

### A.5 What the model does not cover

- **Attacks on the unauthenticated field protocols from inside a zone.** A device inside a level 1 zone can speak Modbus or BACnet to its neighbours in that zone. The zone boundary limits the reach; nothing inside the zone stops it.
- **A compromised Supervisory Command Service or gate.** Both are trusted components. The design narrows what they must be trusted for (re-checks at the command service, signed decisions, an audit chain) but a full compromise of either defeats it.
- **A malicious operator with a valid high role.** Dual approval covers the high-risk tiers; a single operator acting within their role is recorded, not prevented.
- **Physical attack.** Security events are modelled as signals; nothing models an intruder acting on equipment.
- **Vendor-specific firmware flaws.** Devices are behavioural models (SDD 1).
- **Availability attacks on the gate itself**, beyond the rate limits in A8.

### A.6 Rules for the adversarial material

The adversarial scenarios use injected inputs and simulated misbehaviour. They contain no exploit code and target nothing outside the simulator (SDD 10.2). A scenario that would need a working attack on a real product to be written is out of scope.

## Part B. The simulator as software

| # | Threat | Answer | Requirement |
| --- | --- | --- | --- |
| B1 | A protocol server binds to a reachable interface and is mistaken for, or attacked as, real equipment | Refuse to start unless the bind is loopback or a container-internal network; an explicit flag overrides | `ADC-SAF-001` |
| B2 | Agentic-Datacenter code opens an industrial-protocol client connection to a real device | No outbound industrial-protocol connection leaves the simulator's own networks | `ADC-SAF-002` |
| B3 | Simulator signing keys are mistaken for, or replaced by, operator keys | The limits seed is derived from the run seed, held in memory, passed by environment variable, never written to disk; compiled artifacts are labelled non-production; a real operator key is never accepted | SDD 9.2 |
| B4 | A dependency is replaced or a moving reference changes what is run | Frozen lock; REMORA pinned by full commit SHA; actions pinned by SHA; digest-pinned CI image | `ADC-PIN-002`, `ADC-CI-003` |
| B5 | Source text from the reference specification or a standard leaks into the repository | No copied text and no identifying name, kept by review; restricted values kept out of version control until cleared. A scan for hashed forbidden terms is part of CI, but its list of hashes is empty until the owner supplies them, so today the scan checks nothing (`tools/forbidden_terms.sha256`) | `ADC-PRV-001` to `-005` |
| B6 | A licence obligation is triggered unnoticed | The GPLv3 protocol library is confined to one optional package behind a process boundary; licence scan in CI | `ADC-IEC-005`, ADR 0004 |
| B7 | Results are read as claims about a real facility or as certification | Every output states simulation-only, the operating profile, the lowest fidelity level and that no certification is claimed | SDD 1, 6.7, 12.3 |
| B8 | A language-model agent run leaks data or spends money unattended | Model-backed runs are started by a person, only in the `bench` workflow | SDD 12.4 |
| B9 | The benchmark flatters the gate its author wrote | Baseline gates, held-out track, counterfactual replay, preregistration, external result cards | SDD 12.1, 12.3 |

## Assumptions and open items

- The target security levels are assumed, not derived from a risk assessment (SDD 14).
- A9 on the governed path: REMORA's service takes its time from the simulated clock (ADR 0016, decision 3). Scenario `AD-09` is tested with the static allowlist gate (`tests/scenario/test_op13_ad09_governed.py`). No test runs it under `GOVERNED`.
- The data collector has no path in the zone model and is not modelled (`zone_model.md`, section 6, point 1), so its threats are not assessed here.
- This model was written with the design, before the network and governance layers were built. A second review was planned for when they existed. None is recorded.
