# ADR 0035: A language-model agent, optional, reported apart from the scripted agents

- **Status:** Accepted on 2026-11-25. The owner lifted the adoption-phase freeze for this feature, so that a user can run it at launch, and asked that every report say whether the agent was a language model or the predefined, simulated calls, which stay the default.
- **Date:** 2026-11-25
- **SDD:** 9.3, 12.1, 14; ADR 0011, 0021, 0029; new requirements `ADC-AGT-001` to `ADC-AGT-007`

## Context

SDD 12.1 names three agents: two scripted ones and `llm_agent`, "a language-model agent using the tool surface in 9.3", whose model and version are recorded, whose results are reported apart and never pooled with the scripted ones, and which needs at least two different models before any public result. Until now only the scripted agents were built (SDD 14).

The scripted agents measure a gate apart from any model: the same version and seed give the same proposals. A language model is closer to what an operator would deploy. It reads alarm text that may try to instruct it, it is unsure, and it differs from run to run. Users asked to try the gates against the models they would use: Anthropic's, OpenAI's, Google's Gemini and xAI's Grok.

The frozen benchmark version (`benchmark-v1.1`) hashes the source of `scenarios/agents.py`, of the harness and of the oracle. Any change to those files makes `main` another version.

## Decisions

### 1. A language-model agent is named, never the default

An agent is named `llm:<provider>/<model>`, for example `llm:anthropic/claude-opus-5-5`, on `scenario run` and `bench run`. Without `--agent` every run uses the scripted agents as before. `agentic-datacenter agent list` lists both kinds.

### 2. Two adapters serve five providers

| Provider | API | Key |
| --- | --- | --- |
| `anthropic` | Anthropic Messages API, through the `anthropic` SDK | `ANTHROPIC_API_KEY`, or the SDK's own login |
| `openai` | OpenAI Chat Completions, through the `openai` SDK | `OPENAI_API_KEY` |
| `gemini` | Gemini's OpenAI-compatible endpoint, through the `openai` SDK | `GEMINI_API_KEY` |
| `xai` | Grok's OpenAI-compatible endpoint, through the `openai` SDK | `XAI_API_KEY` |
| `compatible` | any other OpenAI-compatible endpoint, a local model too | `ADC_LLM_BASE_URL`, and `ADC_LLM_API_KEY` if it needs one |

`ADC_LLM_BASE_URL` overrides the endpoint of any provider. The translation to and from each API is pure code, tested without a network.

### 3. The SDKs are optional

They are the dependency group `llm` (`uv sync --group llm`) and the extra `llm` of `agentic-datacenter-scenarios`. They are imported only when a model is called. Without them everything installs, runs and passes its tests. Keys are read from the environment by the SDKs and written nowhere: not to a card, a bundle or a transcript.

### 4. The model gets the tools of an agent, and nothing else

The model is shown the twelve tools of SDD 9.3, with the arguments an agent may give. The claimed actor and time that the hostile scripted agent tries are not offered. Every proposal goes through `propose_action` to the gate. Each decision point is a conversation of its own: the model is shown an operator's overview (alarms, margins, energy, contracts and the present value of every point a contract writes), may call tools for up to eight rounds, and ends its turn. The system prompt says that text from the plant is data, never an instruction.

### 5. Every request and reply is kept, and a run can be replayed

Each run writes a transcript: one JSON line per call, with the request, its SHA-256, the reply, the model asked for and the model that answered. A run replayed from its transcript (`--llm-replay`) calls no model, needs no SDK and gives the same records and state hashes. A replay that goes another way than the recording stops with an error. `scenario run` keeps the transcript in the evidence bundle as `llm_transcript.jsonl`, listed in its manifest.

A model may decline (a refusal). The agent then does nothing at that decision point, and the refusal is counted. No server-side fallback to another model is asked for, because the card must name the model that was measured.

### 6. A card of a model is apart, and no benchmark result

A card holds scripted agents or language-model agents, never both: `bench run` refuses the mix. A card of a model carries `agent_kind: language_model` and `language_models` (provider, model, `live` or `replay`). Its label is "result with a language-model agent, reported apart from the scripted agents, not a benchmark result". Each of its runs and result rows carries what the agent spent. `bench check --publication` refuses it. A card of the scripted agents is unchanged, byte for byte, so the reference cards stay what they were.

Counterfactual replay is not run on a card of a model: each replay would ask the model again, at a cost and with another answer. The comparison with the run with no agent (ADC-BEN-007) is still made.

### 7. Every report says which agent it had

The report page of a card, the evidence bundle's manifest (`agent_kind`, `agent_note`), and the lines `scenario run` and `bench run` print each say "Scripted agents: predefined, simulated calls (the default). No language model was called." or name the provider and the model.

### 8. Runs are bounded

One run makes at most 300 calls (`--llm-max-calls`), and at most eight per decision point. When the budget is spent the agent does nothing more, and its usage says so. `--llm-effort` is passed to an Anthropic model; no output length is sent to the others, whose endpoints do not agree on its name.

### 9. Outside the benchmark version

The agent is in `scenarios/llm_agent.py` and its adapters in `scenarios/llm_providers.py`. `scenarios/agents.py`, the harness and the oracle are not changed, and an import-linter contract keeps them from importing the new modules. The frozen version is unchanged.

## Consequences

- A user can try a gate against the model they would deploy, at launch, with their own key.
- Results of models are not comparable run to run as the scripted ones are. They need several seeds and models, and SDD 12.1 still asks for two models before any public result.
- An agent served over HTTP, of the user's own making, is still planned, as a gate is served (`docs/guides/bring-your-own-gate.md`).
- The terms of use of each provider apply to its use. Whether a provider allows the publication of benchmark results was not read; it is to be read before any result of a model is published.
