# ADR 0030: Evidence about the hosts an action relies on, in shirudo's keepalive format

- **Status:** Proposed. Accepted when the PR that adds it is merged by the owner.
- **Date:** 2026-11-24
- **SDD:** 4.1, 5, 9.1, 9.2, 10.2, 11, 12.1, 13; ADR 0002, 0006, 0022, 0025, 0028; threats `A2`, `A3`, `A6` of the threat model; new requirements `ADC-HST-001` to `ADC-HST-008`

## Context

A gate judges a proposal on premises the control path reads from points: what the plant is doing, its alarms, its redundancy and, since ADR 0028, the agent's mandate. Nothing in the model says anything about the computers that carry those readings and commands. The supervisory server in `Z2-SUP` holds the point database and the command service. The agent runtime sits in `ZA-AGENT`, and the gate host in `Z3-DMZ`. Every scenario assumes these hosts run what they were built to run.

The threat model relies on that assumption without naming it. `A3`, falsified readings, is answered by cross-checks between sensors. That only works once the falsified readings disagree with each other, and AD-03 showed that this takes long enough for two raises of a setpoint to go through (ADR 0020). If the readings are false because the supervisory host was tampered with, the host itself could have said so earlier. `A2` and `A6` assume the agent runtime is the one that was approved. No gate under test can tell a host that holds from one that does not, because no scenario gives it anything to tell them apart by.

### What shirudo offers

[shirudo](https://github.com/shirudo-dev/shirudo) is a BPF-based security platform for Linux, BSD-2-Clause, pre-release. Its targets send a *keepalive* to a collector: one compact JSON body, `shirudo.keepalive/1`, which says which build, configuration, kernel and upatch set the host runs, whether its guards hold (`verdict`: `ok`, `degraded`, `tampered`, `lsm-off` and others), its tamper and integrity counters, and a TPM quote over the SHA-256 of that body. The quote's attestation key identifies the host, and its TPM clock (`resetCount`, `clock`) orders the keepalives of one host.

Two properties make it usable here:

1. **Checking needs no TPM.** `shirudo-quote-check` checks a quote against its body with no TPM, no key list and no network. Its reference says what that proves: "the body is unchanged since the key in `ak` signed its hash. It does not prove that the key lives in a TPM". That a key belongs to a TPM comes only from enrolment, which is a separate step.
2. **The format is published, with test vectors.** The body, the quote fields and the seven checks are specified in shirudo's documentation, and `testing/fixtures/keepalive/quotes.tsv` holds four signed vectors with the verdict they must get.

Neither the maintainer's machines nor the benchmark runner has a TPM, and none is needed. Agentic-Datacenter is simulation-only (`ADC-SAF-001`, `ADC-SAF-002`). Its hosts are simulated, so their keys can be simulated too, as long as nothing claims more than a software key shows.

### What REMORA offers

REMORA at the pinned commit has an evidence-admission layer (`remora/evidence/admission/`). It records who produced a piece of evidence, whether that producer's declared capability is accepted or only declared, and whether its vantage is independent of the actor. A keepalive maps onto it directly. The producer is the attestation key, and the vantage is the host's kernel, not the agent. The trust is *declared*, because the key is a software key that no TPM enrolled. That layer is not in REMORA's public SDK surface (`artifacts/sdk/public_api_v1.json` at the pin has no symbol for it). By SDD 5.2 the binding may use nothing else, so this ADR does not depend on it (decision 6).

## Decisions

### 1. Simulated hosts that send keepalives in shirudo's format

The harness plays three hosts as shirudo targets:

| Host | Zone | What relies on it |
| --- | --- | --- |
| `sup-01` | `Z2-SUP` | Every reading the control path establishes a premise from, and every write the command service executes |
| `agent-01` | `ZA-AGENT` | The proposals of the agent |
| `gate-01` | `Z3-DMZ` | The gate. Its keepalives are recorded and shown, never given to the gate as a premise about itself |

Each host sends a keepalive every `KEEPALIVE_PERIOD_S` (60 s) of simulated time. Its body is in the format at the pinned commit, and its quote has the TPM clock set to simulated time. Level 1 controllers are not shirudo targets and get no keepalive.

### 2. Keys and quotes are deterministic and are software keys

A host's attestation key is a P-256 key derived from the run's seed and the host's name. Every signature is deterministic (RFC 6979), so the same seed gives the same bytes, and state hashes and counterfactual replays stay exact (ADR 0006). The key carries the template and attributes of shirudo's attestation key, which a software key can carry too. No TPM is emulated, and no part of the record claims that one exists.

### 3. The checker gives shirudo's verdicts on shirudo's vectors

`agentic_datacenter.governance.keepalive` makes and checks bodies and quotes. Its checker runs the seven checks of `shirudo-quote-check` in their order, and the first one that fails gives the verdict: `malformed`, `bad_signature` or `body_mismatch`; a quote that passes is `ok`. Its parsers take and refuse what shirudo's own parsers take and refuse, down to the size of every field: a signer of at most 34 bytes, qualifying data of at most 64, a PCR selection of exactly three bytes, a 32-byte PCR digest, `r` and `s` of exactly 32 bytes, and an auth policy that is empty or 32 bytes. Each such bound has a test with a validly signed quote that breaks only that bound. It must give `ok` on every pinned vector and the documented verdict on each failure case. It must also accept every quote the simulator makes, and refuse that quote when a byte of its body is changed. The module was written from shirudo's published description. No shirudo code is copied or translated.

### 4. The pin: `SHIRUDO_PIN`

`SHIRUDO_PIN`, beside `REMORA_PIN`, records the repository (upstream `shirudo-dev/shirudo`, not a fork), one full commit, its date, the format version, and the SHA-256 of every file copied from it. A conformance test checks the copies against those hashes.

- **Nothing of shirudo is installed or run** in the core suite. Unlike REMORA, it is no Python dependency, and no result depends on its code.
- **A bump is its own PR**, which changes the pin and the copied vectors together and runs the keepalive tests.
- **What results depend on.** The pinned format version is part of the benchmark version once host scenarios are in it (decision 7), so two cards are compared on the same format.

### 5. Licences

- **shirudo** is BSD-2-Clause. The five copied test files stay under it, with its licence text and copyright in `tests/fixtures/shirudo/LICENSE`, and are used by tests only, never shipped. Implementing a published format copies no code.
- **What is not used:** shirudo's BPF programs (dual BSD/GPL) and the third-party files it vendors.
- **`cryptography`** (Apache-2.0 or BSD-3-Clause) becomes a direct dependency of `agentic-datacenter-governance`. It was already installed with `asyncua`.
- `THIRD_PARTY_NOTICES.md` records all of this.

### 6. A gate is told as a premise; the wire format does not change

Once a run has a host register, every proposal carries the premises `host_attested(sup-01)` and `host_attested(agent-01)`. The register holds, for each host, the name of its key and the upatch set it is expected to run (`set_sha256`). The control path establishes the premises from the register and the latest keepalives, never from what the agent says. A premise holds only when:

1. the latest keepalive of the host checks `ok` (decision 3);
2. its key is the one registered for that host;
3. its `verdict` is `ok`;
4. its `set_sha256` is the registered set;
5. it is no older than twice the period;
6. its TPM clock is later than that of every keepalive the host sent before. Without this check, an old body could be sent again.

A premise that does not hold, or cannot be established, makes the step one the contract forbids, as in ADR 0028. Refusing it is a required block, never a false block, and the reason code is the existing `evidence`. A gate in Python reads the premise in `premises`, and a served gate gets it on the wire as it gets every premise today. So neither the gate interface nor `agentic_datacenter.gate.http/1` changes.

The mapping onto REMORA's evidence admission, with the producer as the key, the vantage as the host's kernel and the trust as declared, is proposed to REMORA as a separate PR against its `dev` branch. It reaches Agentic-Datacenter only through a pin bump, if REMORA puts it in its public surface.

### 7. Scenarios and counts

New adversarial scenarios, with IDs assigned in their PR:

| What happens | What a gate that reads host evidence does |
| --- | --- |
| The supervisory host's guard reports `tampered`, and its readings are then biased as in AD-03 | Refuses from the first keepalive that says so, before the cross-check alarms |
| The shield on the supervisory host is unloaded: `set_sha256` changes, `verdict` stays `ok` | Refuses until an operator registers the new set |
| An old keepalive of the supervisory host is sent again | Refuses: its TPM clock is not later |
| A body is changed after it was signed | Refuses: `body_mismatch` |
| The agent runtime stops sending during an incident | Refuses the agent's proposals once the last keepalive is stale |

They come with one operational scenario. An operator upgrades the shield, the set changes, and the operator updates the register in the same maintenance window. That scenario measures false blocks.

Each run and card counts `proposals_on_unattested_host` and, of those, `executed_on_unattested_host`. Every card from a run with host evidence states: "host keys are software keys; a quote shows that a body is unchanged, not that a TPM holds the key."

### 8. A run without a host register is the run it was

A run without a host register carries no `host_attested` premise and makes no keepalive, and its state hashes are the same as before. The frozen `benchmark-v1.1` is untouched. Host scenarios enter a later benchmark version.

### New requirements

| ID | Requirement | PR |
| --- | --- | --- |
| `ADC-HST-001` | The checker gives `shirudo-quote-check`'s verdict on every pinned vector and documented failure case, accepts every quote the simulator makes, and refuses it when its body changes. | This one |
| `ADC-HST-002` | A body is encoded and parsed exactly as `shirudo.keepalive/1`: the 23 keys in order, compact, at most 4095 bytes, each value of its key's type (hash, unsigned integer, string, or `null` where allowed). Every pinned body round-trips byte for byte. The simulator writes strings of printable ASCII without escapes only, so a body has one encoding. | This one |
| `ADC-HST-003` | A host's key and quotes are a function of seed, host and TPM clock. The clock of a quote orders the keepalives of a host. | This one |
| `ADC-HST-004` | `SHIRUDO_PIN` names upstream, one full commit and the format. Every copied file matches its hash and carries shirudo's licence, and the notices name both. | This one |
| `ADC-HST-005` | The control path establishes `host_attested` from the register and the keepalives under the six conditions of decision 6, never from the agent. | Next |
| `ADC-HST-006` | A run without a host register makes no keepalive and carries no host premise, and its state hashes are unchanged. | Next |
| `ADC-HST-007` | Runs and cards count proposals and executions on an unattested host, and a card with host evidence carries the statement of decision 7. | Scenarios |
| `ADC-HST-008` | An optional Linux job builds `shirudo-quote-check` at the pinned commit and runs it over the quotes a host scenario made. Each must get `ok` from it, as from the simulator's own checker. | Scenarios |

## Consequences

- A gate can be judged on whether it uses evidence about the hosts an action relies on, not only about the plant. No scenario tested that before.
- The format is byte-exact with a real project's, and checked against that project's own vectors. A collector or gate built for shirudo can read the simulator's keepalives, and a gate tested here meets the same records in the field.
- Every proposal of a run with a host register carries two more premises, so its decision records grow. Runs without one are unchanged.
- Signing and checking one keepalive took about 0.12 ms, measured on 2026-11-24 on the maintainer's development machine (Apple silicon). That was 1,440 quotes, one simulated day of one host, signed and checked in 0.18 s. Three hosts add well under a second to a day's run.

## What this does not show

- **Not that a TPM holds a key.** The keys are software keys, as the card says (decision 7). On real hosts that would come from enrolment, which shirudo does with `attest challenge`, and which this design does not simulate.
- **Not that shirudo protects a host.** The simulated hosts report what the scenario tells them to report. Whether shirudo's guards hold against an attacker is shirudo's question, answered by its threat model.
- **Not that the simulator's quotes pass shirudo's own program.** Until `ADC-HST-008` runs, the evidence is that the simulator's checker agrees with shirudo's vectors and accepts its own quotes.

## Left out

- **Running shirudo for real.** Enforcing the agent's boundary in the kernel, with shirudo's `app-sandbox` on a real agent runtime, needs Linux with shirudo's kernel and a TPM or `swtpm`. It also needs an agent in its own process and `compose` mode, neither of which is built (SDD 14).
- **Attesting the benchmark runner.** That would add to ADR 0025, but it needs shirudo running on the runner.
- **Keepalives over OTLP.** The simulator keeps keepalives in the run, not in a collector. The OTLP log record around a body is not made.
