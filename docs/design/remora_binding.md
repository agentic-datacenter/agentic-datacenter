# REMORA binding: what Agentic-Datacenter asks of REMORA

SDD-ADC-001, section 9.2, required the binding surface to be checked against the pinned REMORA commit before any binding code was written. That check was made on 2026-11-12, against the first pin. This file keeps what is still in force: where the design document differs from REMORA, how the `DECISION_ONLY` binding maps a proposal onto REMORA's policy function, and what was found when the governed path was built. The current pin is in `REMORA_PIN`.

## 1. Where the design document differs from REMORA

Found in the check of the first pin. The code follows REMORA. The sentences in the design document were not changed.

| Design document | REMORA, and what the code does |
| --- | --- |
| 5.2: the binding depends on REMORA "with the `security` extra" | The governed client needs `httpx`, which only the `sdk` extra provides, and the in-process service needs the `api` extra (ADR 0016). `packages/agentic-datacenter-remora/pyproject.toml` depends on `remora-assurance[security,sdk,api]` |
| 9.2: "Consume and execute: `execute()`" | Two calls. `execute_accepted(execution_token, tool_call)` redeems the token of a proposal that was accepted outright. `execute(review_item_id, tool_call)` runs one that a person approved, and may return a pending execution when the service dispatches asynchronously. The binding treats a pending execution as outcome unknown, never as applied (ADR 0016) |
| `ADC-PIN-006`: the maturity word is ESTABLISHED, PARTIAL or NOT\_ESTABLISHED | At the first pin the `status` field of the capability register had five values: `IMPLEMENTED_LIBRARY`, `WIRED_REFERENCE_PATH`, `WIRED_API_PATH`, `PERSISTED_ATOMIC` and `NOT_ESTABLISHED`. The rule itself, to reproduce the register's word unchanged, does not depend on the list |
| 9.2: "REMORA's own register lists [rollback] as PARTIAL" | Not found at the first pin: no capability entry in the four register files is named for rollback. The split is Agentic-Datacenter's own description: REMORA reports `rollback_available` and verifies effects; trigger and restore belong to Agentic-Datacenter |

The first two rows hold at the current pin, because the code depends on them. The last two were read from the registers at the first pin and have not been read again since.

## 2. The `DECISION_ONLY` binding: what Agentic-Datacenter tells REMORA

`packages/agentic-datacenter-remora/src/agentic_datacenter_remora/binding.py` uses four public symbols and nothing else: `evaluate_policy`, `PolicyObservation`, `GateDecision` and `GateVerdict`. A test exports the public API snapshot from the installed package and requires every imported symbol to be in it.

**This mapping is Agentic-Datacenter's interpretation and has not been confirmed by the REMORA maintainer.** It decides what REMORA is asked, so it decides what the benchmark measures.

### 2.1 Refused before the policy is asked

A proposal that cannot be formed has no approvable path: the contract does not exist, the contract is risk tier `R3`, the arguments do not fit, or there is nothing to write. The binding builds the refusal with `GateDecision.deny(...)`, as that constructor's own documentation describes, and the policy function is not called.

### 2.2 The observation

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

### 2.3 What comes back, observed at the pin

| Situation | REMORA action and first reason | Agentic-Datacenter verdict |
| --- | --- | --- |
| `R1`, every premise holds | ACCEPT, `ordered_high_trust` | ALLOW |
| A premise could not be established | ABSTAIN, `disordered_no_evidence` | ABSTAIN |
| A premise does not hold | ABSTAIN, `evidence_contradicted` | ABSTAIN |
| A write outside bounds or step | ESCALATE, `malformed_call_blocked` | VERIFY, escalated, two approvers |
| `R2`, every premise holds | VERIFY, `evidence_insufficient` | VERIFY, with the approvers the contract names |

If REMORA accepts a contract whose own approval rule asks for a person, the verdict is VERIFY: the contract's rule stands.

### 2.4 What needs the maintainer's eye

1. **`phase` and `trust_score` are REMORA's consensus signals, and Agentic-Datacenter has no model ensemble behind them.** They are set from deterministic premise checks: "every premise the contract names was read fresh, in good quality, and holds" is reported as `ordered` with trust 1.0. Without them `evaluate_policy` never accepts anything (`default_safe_abstain`). Whether a host may stand in for those signals this way, or whether another field is meant for host-verified preconditions, is the question.
2. **A premise that does not hold gives ABSTAIN, not DENY.** The scenario table expects "deny" in several places (OP-03, OP-11). The pure decision never returns DENY, so under `DECISION_ONLY` these are abstentions. Both count as blocked.
3. **A write outside its bounds is escalated to two approvers rather than refused.** That is REMORA's decision on `schema_valid = false`. On the governed path the ToolSpec would refuse it. The approval path re-reads bounds and would reject, so nothing unsafe executes, but an approver is asked a question with only one answer.
4. **Rate and cumulative limits are not enforced.** The control path computes them and the binding reports them in the decision detail as not enforced. Scenarios AD-04 and AD-05 cannot be claimed under this profile, as the design document says.

## 3. The governed path

Built on the pin that carries `remora build-toolspec` and the SDK hand-over of the observed effect (REMORA #1232). How REMORA's service is embedded, what each contract field compiles to, and what stays with the binding is in ADR 0016. Three findings from driving the path are recorded as REMORA issue 1233 and are not worked around:

1. No write is accepted without a person; low and medium tier writes are not reviewable without a semantic bundle and a resolved intent.
2. The signed ToolSpec and the tool metadata file are not cross-checked, so a tool declared `read` in the metadata is accepted although its signed spec says `write`.
3. A host cannot state through the SDK that a call did not run; such a call is held as unknown until a reviewer resolves it.

The check of the first pin left six questions about the governed path. Their answers: time on the governed path is answered by the host time source (REMORA #1221); approver identity by one credential per person; the resolver of an unknown outcome is a reviewer principal with Agentic-Datacenter's evidence module; limit arithmetic is in thousandths, recorded in the compile manifest; the counter is keyed by point through a shared quantity; asynchronous dispatch is treated as unknown.
