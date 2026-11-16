# REMORA binding: interface discovery at the pinned commit

Stage 0 deliverable required by SDD-ADC-001, section 9.2 ("Binding rule"). It records what was checked against the pinned REMORA commit, what matched, what did not, and what is still unverified.

- **Checked on:** 2026-11-12
- **Pin:** tag `dcsim-pin-2026-11-12b`, commit `dfc44de2b4ebc579b0c5e76c541eeecd414961d6` (see `REMORA_PIN`)
- **Result:** the surface in SDD 9.2 exists at the pin. Three statements in the SDD differ from the code and one could not be confirmed; they are listed in section 3 as proposed SDD changes. Nothing was patched around in Agentic Datacenter.

## 1. Method

Two independent sources were used, and nothing was executed from an unpacked tree.

1. **The installed package.** `agentic-datacenter-remora` declares `remora-assurance` as a Git dependency at the pinned commit. `uv lock` and `uv sync --all-groups` resolved and installed it; the SDK was imported and the packaged CLI was run from that environment.
2. **The Git tree at the pin**, read as data with `git show <sha>:<path>` from a clone of the REMORA repository. Used for files that are outside the wheel (registers) and for reading source.

Status words used below: **CONFIRMED** (seen in the code or by running it), **DIFFERS** (exists, but not as the SDD states), **NOT CONFIRMED** (looked for, not found), **NOT EXERCISED** (present, but only read, not run).

## 2. Verification record

### 2.1 Pin and package

| SDD statement (section) | Result | Evidence |
| --- | --- | --- |
| Tag `dcsim-pin-2026-11-12b` is an annotated tag, object `80a290e4…`, on commit `dfc44de2…` (5.2) | CONFIRMED | `git rev-parse` of the tag and of `tag^{commit}` |
| Tag `dcsim-pin-2026-11-12` is object `2e7d6b08…` on commit `c26a092d…` (5.2) | CONFIRMED | Same |
| The pinned commit originates on `dev` (5.2) | CONFIRMED | It is an ancestor of `origin/dev`; it is the merge commit of REMORA #1220 |
| Distribution `remora-assurance`, import name `remora`, version 0.12.0, hatchling, packages `remora` and `servers` (5.2) | CONFIRMED | `pyproject.toml` at the pin; installed metadata reports 0.12.0 |
| The `security` extra is what the signing command needs (5.2) | CONFIRMED | `security = ["cryptography>=50.0.0"]`; `sign-limits` exits with a message naming the extra when it is absent |
| `agentic-datacenter-remora` depends on it "with the `security` extra" (5.2) | DIFFERS | `RemoraClient` imports `httpx`, which only the `sdk` extra provides. The binding needs `security` and `sdk`. See 3.1 |
| Installs at the pinned commit as a normal Git dependency through `uv` (5.2) | CONFIRMED | `uv.lock` records `…REMORA-research?rev=dfc44de2…#dfc44de2…` |
| The installed commit can be compared with `REMORA_PIN` at run time (5.2, ADC-PIN-003) | CONFIRMED | The installed distribution's `direct_url.json` carries `vcs_info.commit_id` with the full SHA |

Not stated in the SDD and relevant to ADR 0004: REMORA declares its licence as `BUSL-1.1` with a separate commercial licence, and requires Python 3.11 or later.

### 2.2 Packaged CLI

| SDD statement (section) | Result | Evidence |
| --- | --- | --- |
| `remora export-contract-files <dir>` writes `public_api_v1.json`, `openapi.json` and the ToolSpec schemas `tool_spec_v1` to `v5` and `toolspec_signing_ed25519_v1` from the installed wheel (5.2) | CONFIRMED | Ran from the installed package: 8 files written. The six schema files are YAML. `public_api_v1.json`, `openapi.json` and `tool_spec_v5.yaml` were compared byte for byte with the tree at the pin and are identical |
| The public API snapshot has 46 symbols; recount at the current pin (5.2) | CONFIRMED | 46 symbols in the exported file, module `remora.sdk`, snapshot version 1 |
| `remora sign-limits <policy> --out <limits.json>` validates and signs a limit policy (5.2, 9.2) | CONFIRMED, NOT EXERCISED | Subcommand present with positional `policy` (JSON or YAML), `--out` and `--new-key`. Run without arguments it answers "policy and --out are required". No policy has been signed yet because no Agentic Datacenter contract has been compiled |
| Signing key is supplied as a seed in `REMORA_LIMITS_SIGNING_SEED` (9.2) | CONFIRMED | Read by the command; it refuses to run when unset and prints the public key to trust on stderr |
| Policy schema `remora-cumulative-limits/v1`, signed form `remora-cumulative-limits-signed/v1`, field `dual_control_above` (9.2) | CONFIRMED | Both identifiers and the field are in the cumulative-limits module and the CLI |
| There is no packaged `remora build-toolspec`; the only flow is `deploy/ot-pilot/build_toolspec.py` (5.2, 9.2) | CONFIRMED | No such subcommand in the CLI; the pilot script exists at the pin. Stage 8 entry condition is therefore still unmet |
| A YAML limit policy can be passed | CONFIRMED with a condition | The command needs PyYAML for YAML input and says so; JSON needs nothing extra |

### 2.3 SDK surface (`remora.sdk`)

| SDD statement (section 9.2) | Result | Evidence |
| --- | --- | --- |
| `evaluate_policy(observation, *, caps=(), engine=None)` | CONFIRMED | Signature read from the installed function |
| It takes a `PolicyObservation` and returns a `GateDecision` with verdict, action, reasons, `escalated`, `human_review_required`, `evidence_required`, explanation, resolution plan | CONFIRMED | Frozen dataclass with exactly those fields |
| It is pure: no clock, no randomness | CONFIRMED as documented, weakly exercised | Stated in the module and function docstrings. Two calls with one observation returned equal decisions. This is a smoke check, not the proof; `property/test_determinism` must still cover it (9.2) |
| The pure decision never returns DENY; a host builds it with `GateDecision.deny(...)` | CONFIRMED | The action-to-verdict map has no DENY entry. `deny()` sets verdict DENY and action ABSTAIN |
| ACCEPT to ALLOW, VERIFY to VERIFY, ESCALATE to VERIFY with `escalated` true, ABSTAIN to ABSTAIN | CONFIRMED | `verdict_for_action` and the `escalated` assignment |
| `RemoraClient.assess()` returns, on accept, a signed single-use `execution_token` bound to `tool_call_hash` | CONFIRMED, NOT EXERCISED | `AssessmentResult` has `proposal_id`, `action`, `tool_call_hash`, `execution_token`, `review_item_id`. No service was started |
| `get_review_packet()`, `approve()`, `reject()` | CONFIRMED, NOT EXERCISED | All three exist. `reject` requires a reason. `approve` takes a time limit, default 900 s |
| "Consume and execute: `execute()`" | DIFFERS | Two calls exist. `execute_accepted(execution_token, tool_call)` redeems an ACCEPT token. `execute(review_item_id, tool_call)` runs an approved review item. See 3.2 |
| A second execute on the same grant is refused with `ReplayRefusedError` | CONFIRMED, NOT EXERCISED | The exception is public and documented on `execute_accepted`, together with `ApprovalExpiredError` and `BindingRefusedError` |
| `record_effect()`, `verify_audit_chain()`, `export_evidence()` | CONFIRMED, NOT EXERCISED | All three exist |
| `list_unresolved()`, `resolve_unknown()` | CONFIRMED, NOT EXERCISED | Both exist. Conditions that matter to Agentic Datacenter are in section 4 |
| REMORA keeps the `tool_call_hash`, not the raw arguments; the review packet carries the hash | CONFIRMED | `ReviewPacketView` has `tool_call_hash`, `arguments_available` and `arguments_note`, and no arguments |
| The binding can compute `tool_call_hash` deterministically and set it on the observation | CONFIRMED | `PolicyObservation.tool_call_hash` exists. `PolicyObservation.from_tool_call(...)` fills it with a SHA-256 over the canonical name, arguments, tenant and target. That constructor is reachable through `remora.sdk`. The underlying helper function is not a public symbol, so the binding must use the constructor |
| `rollback_available` is reported by REMORA | CONFIRMED | Field on `ToolCall` and on `PolicyObservation` |
| "REMORA's own register lists this [rollback] as PARTIAL" | NOT CONFIRMED | See 3.4 |
| In `compose` mode the REST contract is `schemas/openapi.json` at the pin | CONFIRMED | The file exists and is included in the wheel |

### 2.4 Registers in the Git tree

All four files named in SDD 9.2 exist at the pin: `docs/assurance/capability_register_v1.yaml`, `docs/interop/remora-capabilities-v1.yaml`, `docs/interop/remora-boundaries-v1.yaml` and `artifacts/interop/remora-boundary-summary-v1.json`. They are outside the wheel, as the SDD says, so `agentic-datacenter remora fetch-src` is still needed.

| SDD statement | Result | Evidence |
| --- | --- | --- |
| CAP-031 is the cumulative-limits capability (9.2) | CONFIRMED | Entry CAP-031, "Cumulative limits per principal or resource, reserved before dispatch (opt-in)", status `WIRED_API_PATH` |
| The maturity word is one of ESTABLISHED, PARTIAL or NOT_ESTABLISHED (ADC-PIN-006) | DIFFERS | See 3.3 |

## 3. Differences and proposed SDD changes

The SDD is changed first, by PR. These are proposals for the owner; none has been applied to the SDD.

### 3.1 The binding needs the `sdk` extra as well as `security`

`remora.sdk` loads `RemoraClient` lazily because it needs `httpx`, and REMORA ships that only in the `sdk` extra. With `security` alone the pure decision works and every governed call fails on import.

- **Done in this PR:** `packages/agentic-datacenter-remora/pyproject.toml` depends on `remora-assurance[security,sdk]`.
- **Proposed SDD text, 5.2 "Pinned resource":** "`agentic-datacenter-remora` depends on it with the `security` extra, which the signing command needs, and the `sdk` extra, which the governed client needs."

### 3.2 Two execute calls, not one

The table in 9.2 names `execute()` for "Consume and execute". At the pin:

- `execute_accepted(execution_token, tool_call)` is the path for a proposal that was accepted outright. The token is the authorization.
- `execute(review_item_id, tool_call)` is the path after a human approval. It may return `PendingExecution` instead of `ExecutionResult` when the service runs with asynchronous dispatch.

Both re-send the full call so the service can re-bind it. The order of operations in "Rules for the binding" is unaffected.

- **Proposed SDD text, 9.2 table:** "Consume and execute | `execute_accepted()` for ACCEPT, `execute()` after approval | …"
- **Proposed addition to the rules:** the binding treats a `PendingExecution` as outcome UNKNOWN until the proposal view reports a dispatch result, and never as applied.

### 3.3 `ADC-PIN-006` names a vocabulary the register does not use

The capability register's `status` field has five values at the pin: `IMPLEMENTED_LIBRARY`, `WIRED_REFERENCE_PATH`, `WIRED_API_PATH`, `PERSISTED_ATOMIC` and `NOT_ESTABLISHED`. `ESTABLISHED` and `PARTIAL` are not status values there. The interop declaration uses a third list (`DECLARED` to `OPERATOR_OBSERVED`), and the boundary register a fourth.

The rule itself (reproduce the word unchanged) is sound and does not depend on the list.

- **Proposed SDD text, `ADC-PIN-006`:** replace "(ESTABLISHED, PARTIAL or NOT\_ESTABLISHED)" with "(whatever status value that register holds for the capability at the pin; Agentic Datacenter does not translate or rank these words)".
- **Needs an owner decision:** which of the four registers is the source for the IEC 62443 matrix. The capability register is the only one keyed by `CAP-nnn`.

### 3.4 Rollback "PARTIAL" could not be found

Section 9.2 says REMORA's own register lists rollback as PARTIAL. The word occurs once across the four register files, in the boundary register, on an entry about an external vocabulary project and not about rollback. No capability entry is named for rollback.

- **Proposed SDD text:** state the split as Agentic Datacenter's own description ("REMORA reports `rollback_available` and verifies effects; trigger and restore belong to Agentic Datacenter") and drop the attribution to a register, or cite the register entry by identifier once the maintainer points to it.

## 4. Conditions the binding has to meet (for Stage 8)

Found while reading the surface. None blocks Stage 0; each needs a design answer before the governed path is built.

| Topic | What the pin requires | Consequence for Agentic Datacenter |
| --- | --- | --- |
| Governed path is a service | `RemoraClient` speaks REST to a control plane. Its constructor accepts a prepared `httpx.Client`, documented for in-process use against the application object | `inproc` mode needs the REMORA service running in-process behind that client. Which extra and entry point that takes was not verified |
| Time in the governed path | Tokens and approvals expire; an unresolved operation carries a timestamp | It is not yet known whether the service can take its time from the simulated clock. This decides how `AD-09` is run and whether `SHADOW` and `GOVERNED` can be reproducible end to end. Tokens are already outside the state hash (9.2), which limits the damage. To be raised with the maintainer |
| Approver identity | The approver recorded is the authenticated principal of the caller's token; an "on behalf of" value is an annotation only | The scripted operator model needs its own credentials, and `two_person` needs two distinct principals |
| Resolving an unknown outcome | The resolver must not be the principal the call was charged to, and must name evidence that the service checks through the deployment's evidence module | `ADC-GOV-007` needs a reviewer identity separate from the agent, and Agentic Datacenter must supply the evidence module backed by an independent read of plant state |
| Limit arithmetic | The limit fields seen (`dual_control_above`, the charge amount) are integers | A contract limit such as a total change of 2.0 °C must be compiled to an integer unit. The scaling belongs in `agentic-datacenter contracts compile` and must be recorded in the artifact |
| Limits across contracts | CAP-031 is described as per principal or resource, and is opt-in | `INV-GOV-6` needs the counter keyed by tag, not by contract. To be confirmed when the first limits file is compiled |
| Async dispatch | See 3.2 | Binding branch on the result type |

## 5. Gaps recorded for REMORA

Per the binding rule these are recorded here rather than worked around. They should become issues against REMORA's `dev` branch; none has been filed from this repository.

1. A packaged `remora build-toolspec` (already known; Stage 8 entry condition).
2. A statement, or a supported hook, for the time source of the governed path when REMORA is embedded in a simulator.
3. Which register and which field a host should quote for capability maturity (3.3), and where rollback is recorded (3.4).

## 6. How to repeat this check

```sh
uv sync --all-groups
uv run --all-groups remora export-contract-files /tmp/remora-contract-files
uv run --all-groups python -c "import remora.sdk as s; print(len(s.__all__))"
git -C <remora clone> rev-parse 'dcsim-pin-2026-11-12b^{commit}'
```

The last command must print the commit in `REMORA_PIN`.

## 7. The `DECISION_ONLY` binding: what Agentic Datacenter tells REMORA

Added with Milestone M1. `packages/agentic-datacenter-remora/src/agentic_datacenter_remora/binding.py` uses four public symbols and nothing else: `evaluate_policy`, `PolicyObservation`, `GateDecision` and `GateVerdict`. A test exports the public API snapshot from the installed package and requires every imported symbol to be in it.

**This mapping is Agentic Datacenter's interpretation and has not been confirmed by the REMORA maintainer.** It decides what REMORA is asked, so it decides what the benchmark measures.

### 7.1 Refused before the policy is asked

A proposal that cannot be formed has no approvable path: the contract does not exist, the contract is risk tier `R3`, the arguments do not fit, or there is nothing to write. The binding builds the refusal with `GateDecision.deny(...)`, as that constructor's own documentation describes, and the policy function is not called.

### 7.2 The observation

Built with `PolicyObservation.from_tool_call`, which also computes `tool_call_hash`.

| Observation field | Set from | Value |
| --- | --- | --- |
| `name`, `arguments` | The contract id and the proposal's arguments | As proposed |
| `risk_tier` | The contract's risk tier | `R0`, `R1` → `low`; `R2` → `high` |
| `domain`, `action_type`, `target_environment` | Constants | `operational-technology`, `write`, `simulation` |
| `schema_valid` | Contract bounds and step | False when any write is outside them |
| `rollback_available` | The contract | True when it declares a rollback |
| `evidence_supporters`, `evidence_contradictions` | The premises the control path read | Counts of premises that hold and that do not |
| `phase` | Whether every premise could be established | `ordered` when all were; `disordered` when any was stale, of bad quality or too old |
| `trust_score` | The same | 1.0 when every premise was established and none failed; otherwise unset |

Nothing the agent wrote reaches the observation except the contract id and arguments: not its rationale, not who it claims to act for. A test asserts that two proposals differing only in those give the same decision and the same decision reference.

### 7.3 What comes back, observed at the pin

| Situation | REMORA action and first reason | Agentic Datacenter verdict |
| --- | --- | --- |
| `R1`, every premise holds | ACCEPT, `ordered_high_trust` | ALLOW |
| A premise could not be established | ABSTAIN, `disordered_no_evidence` | ABSTAIN |
| A premise does not hold | ABSTAIN, `evidence_contradicted` | ABSTAIN |
| A write outside bounds or step | ESCALATE, `malformed_call_blocked` | VERIFY, escalated, two approvers |
| `R2`, every premise holds | VERIFY, `evidence_insufficient` | VERIFY, with the approvers the contract names |

If REMORA accepts a contract whose own approval rule asks for a person, the verdict is VERIFY: the contract's rule stands.

### 7.4 What needs the maintainer's eye

1. **`phase` and `trust_score` are REMORA's consensus signals, and Agentic Datacenter has no model ensemble behind them.** They are set from deterministic premise checks: "every premise the contract names was read fresh, in good quality, and holds" is reported as `ordered` with trust 1.0. Without them `evaluate_policy` never accepts anything (`default_safe_abstain`). Whether a host may stand in for those signals this way, or whether another field is meant for host-verified preconditions, is the question.
2. **A premise that does not hold gives ABSTAIN, not DENY.** The scenario table expects "deny" in several places (OP-03, OP-11). The pure decision never returns DENY, so under `DECISION_ONLY` these are abstentions. Both count as blocked.
3. **A write outside its bounds is escalated to two approvers rather than refused.** That is REMORA's decision on `schema_valid = false`. On the governed path the ToolSpec would refuse it. The approval path re-reads bounds and would reject, so nothing unsafe executes, but an approver is asked a question with only one answer.
4. **Rate and cumulative limits are not enforced.** The control path computes them and the binding reports them in the decision detail as not enforced. Scenarios AD-04 and AD-05 cannot be claimed under this profile, as the design document says.

## 8. The governed path (Stage 8)

Built on the pin that carries `remora build-toolspec` and the SDK hand-over of the observed effect (REMORA #1232). How REMORA's service is embedded, what each contract field compiles to, and what stays with the binding is in ADR 0016. Three findings from driving the path are recorded as REMORA issue 1233 and are not worked around:

1. No write is accepted without a person; low and medium tier writes are not reviewable without a semantic bundle and a resolved intent.
2. The signed ToolSpec and the tool metadata file are not cross-checked, so a tool declared `read` in the metadata is accepted although its signed spec says `write`.
3. A host cannot state through the SDK that a call did not run; such a call is held as unknown until a reviewer resolves it.

Of the conditions in section 4: time on the governed path is answered by the host time source (REMORA #1221); approver identity by one credential per person; the resolver of an unknown outcome is a reviewer principal with Agentic Datacenter's evidence module; limit arithmetic is in thousandths, recorded in the compile manifest; the counter is keyed by point through a shared quantity; asynchronous dispatch is treated as unknown.
