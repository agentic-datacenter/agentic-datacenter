# Changelog

Changes that matter to someone using or reviewing Agentic-Datacenter. Each distribution follows semantic versioning once it has a first release; until then everything is version 0.0.0.

## Unreleased

No version has been released, and no benchmark result has been reported. This entry describes the repository as it is first made public: what it can do, what it cannot do yet, and the most recent changes. The history before that is in the git log and in the decisions under `docs/design/adr/`.

### What it can do

Plant and protocols

- A generic simulated data center (`profiles/generic_dc.yaml`) built from sixteen plant modules: utility supply, medium-voltage switchgear with protection relays, power trains with automatic transfer, generators, UPS, IT load, weather, chillers, thermal storage, pumps, PODs, electrical rooms, sensors, fuel, life safety and security. Every module is at fidelity `F1`. None is calibrated against a real facility.
- A deterministic kernel on simulated time. The same profile and seed give the same state hash, and a run can be captured and restored.
- A supervisory layer: point database, alarms, append-only hash-chained logs, sessions with four permission levels, a historian, and an operator API. Every write goes through one command service.
- IEC 62443 zones and conduits as data. Every request between zones is decided against the conduit model, and a refusal is logged.
- Simulated Modbus/TCP, BACnet/IP, SNMPv3, OPC UA and IEC 61850 MMS servers, read from the point database. The IEC 61850 package is GPLv3, serves on Linux only, and generates its SCL files (`agentic-datacenter scl export`). Servers bind only inside the simulator's own networks.
- Measured weather series as input to a scenario (`docs/guides/measured-weather.md`). No dataset is in the repository.

Governance gates and the REMORA binding

- A gate interface with four verdicts (`ALLOW`, `DENY`, `VERIFY`, `ABSTAIN`), a contract library (`contracts/`), and invariants that hold whatever the gate (`docs/reference/invariants.md`).
- Built-in gates: `null_gate`, `static_allowlist`, and three bindings to REMORA: `remora` (`DECISION_ONLY`), `remora_governed` (`GOVERNED`) and `remora_shadow` (`SHADOW`).
- REMORA is pinned by commit in `REMORA_PIN` and imported by one package only. The REMORA gates refuse to start unless the installed REMORA is the pinned commit. `agentic-datacenter contracts compile` turns the contract library into a signed ToolSpec bundle and a signed limit policy with REMORA's own tools.
- Gates from other projects: a Python package, a service over HTTP in any language (`http_gate`, wire format `agentic_datacenter.gate.http/1`), or a command per decision (`command_gate`). `agentic-datacenter gate check` runs the interface suite against any of them (`docs/guides/bring-your-own-gate.md`).

Scenarios and benchmark

- Twenty-three scenarios, thirteen operational and ten adversarial, played by scripted agents: careful, hostile, drifting and flooding.
- Counterfactual replay: a blocked proposal is replayed as if it had been carried out, to show whether the block avoided harm or cost a useful step. Every run is also compared with the same scenario and seed with no agent.
- `agentic-datacenter bench run` in four tiers (`docs/bench/TIERS.md`), in several processes or split over machines and merged. The result card is the same, byte for byte, however it was made.
- `agentic-datacenter demo`: three scenarios with no gate and with one, from the same seed, as a page with every decision and its record and as a one-page result report in HTML and Markdown.
- `agentic-datacenter whatif`: one proposed change played as a baseline, a physical branch and a governed branch.
- For a public test: `agentic-datacenter bench freeze`, hidden scenario variants drawn from a public randomness beacon, and a preregistration (`docs/bench/PUBLIC_TEST.md`, `docs/bench/PREREGISTRATION.md`).

Evidence and release check

- An evidence bundle per run: manifest, state hashes, decision records, change log and metrics. `agentic-datacenter scenario verify` checks a bundle against its manifest.
- `agentic-datacenter bench check` refuses a result card with a harmful execution, an invariant breach, a failed scenario criterion, a run with more harm than the same run with no agent, or anything missing (`docs/guides/release-gate.md`).
- `tools/gen_62443_matrix.py` writes the IEC 62443 matrix from a test run. No conformance is claimed.

Tooling

- Ten Python distributions in one `uv` workspace with one lock, and import-linter contracts for the boundaries between them.
- Requirement traceability: tests carry the requirement they verify, and `tools/traceability.py` fails when a requirement that is due has no passing test or no owner. `docs/reference/requirements.md` lists which requirements are due and which are still open.
- Reference pages generated from the code, and a strict documentation build.
- Workflows whose jobs run in one digest-pinned image, the benchmark runner excepted, with `tools/ci_local.py` to run the same jobs on a machine of your own.
- A devcontainer for GitHub Codespaces.

### What it cannot do yet

- `compose` mode is not built. Everything runs in one process (`inproc`).
- There is no language-model agent. The agents are scripted.
- The benchmark version is not frozen, and every run so far is a development run.
- No result has been reproduced on a second machine.
- The other differences from the design document are in its section 14.

### Recent changes

Added

- A one-page result report, written by `agentic-datacenter demo` as `executive.html` and `executive.md`. It opens with the result, has a chart per scenario, and states what a simulated result does not show. The committed example is `docs/demo/result-report.md`, made from `docs/demo/demo.json` by `tools/demo_example.py`.
- `agentic-datacenter bench record` writes `provenance.json` beside a result card: the commit of the code and the SHA-256 of every file the benchmark made. `bench verify` checks the files against it. The benchmark runner attests the record, and a release attests every wheel and source distribution with its build provenance and a bill of materials (ADR 0025). The attesting steps run on a public repository only; none has run yet.
- Every distribution carries the text of its licence, and `tools/check_dist_licences.py` checks every built wheel and source distribution for it. `COMMERCIAL_LICENSING.md` names the Licensor and the commercial licensing representative.
- `.github/workflows/bench-runner.yml`: a benchmark on a self-hosted runner, started by hand. The guide, with how much memory a long run needs, is `docs/guides/bench-runner.md`.
- `agentic-datacenter demo --scenario <id>` plays one demonstration scenario. `OP-03` alone takes about a minute.
- A pin bump now carries the metric difference against the previous pin (`tools/pin_diff.py`, the `pin-bump` workflow), and the 62443 matrix names the REMORA capabilities it credits with the maturity word of REMORA's own register. Every requirement of the design document now has a passing test and an owner; what is still not built is in its section 14.

Changed

- The committed three-scenario example and its result report compare no control with `remora_governed`. Before, they compared it with `static_allowlist`.
- Benchmark judging (ADR 0024): a step is not a false block when its contract requires approval, the gate asked at least the people the contract requires, and a person declined or did not answer. Such steps are counted apart as `approvals_declined`. No safety figure changes. Card schema version 5; `bench check` refuses a card of an older schema.
- A block the contract itself requires is counted as `required_blocks`, not as a false block (`docs/bench/FAIRNESS.md`, rule 5).
- With `--jobs`, the longest runs of a benchmark start first.
- `THIRD_PARTY_NOTICES.md` lists only what is used. Datasets suggested for later calibration are in `docs/calibration/suggested_resources.md`.
- Test files are named by what they test, not by when they were written.
- A run judged by counterfactual replay keeps a copy of the plant's state only where a branch will start from it. For a gate restored from its own snapshots (`remora_governed`) that is the instants to be judged, at most 16 in `OP-10`, where it was all 671 decision points, twice. Each copy is released when its last branch has started. One `standard` run of `OP-10` with the hostile agent peaked at 0.32 GB on 2026-11-17; it held 3.3 to 3.8 GB before.
- No result changes. Cards made before and after, for `OP-10`, `AD-08` and `OP-08` under five gates and with one and three jobs, are the same byte for byte except the hash of the oracle's source in `benchmark_version`, which changes because `harness.py` and `counterfactual.py` are part of it; no version was frozen.
- `docs/guides/bench-runner.md` gives the new figures: allow 0.4 GB for each job with `remora_governed`.

Fixed

- IEC 61850 client: `MmsClient` no longer answers `connection-lost` on a connection that is open. On a loaded machine the library could leave a new association marked as still being made (ADR 0017, addendum).
- `bench check` refuses an incomplete card. Missing figures are no longer read as zero.
- The unsafe execution rate is over the executed proposals that were judged, and harm is judged per dimension, never summed across units.
