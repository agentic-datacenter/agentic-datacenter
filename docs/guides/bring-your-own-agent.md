# Bring your agent: a language model

A language model can now be the agent. It runs in the same facility, scenarios and seeds as the scripted agents, under each safety control, through a provider's API with your own key. It is optional: without it every run uses the scripted agents, whose calls are predefined and simulated, and every report says which kind of agent it had. An agent of your own making, served over HTTP, is still planned.

## Try it without a key

The repository holds one recorded run. It was made by a scripted stand-in, not a model, to show what a run of a model gives. Replaying it calls nothing and needs no key or network:

```sh
uv run agentic-datacenter scenario run OP-03 --seconds 900 --agent llm:compatible/stand-in \
  --llm-replay examples/llm-agent/OP-03.jsonl --out build/llm-example
```

The run prints `agent: llm:compatible/stand-in. Language-model agent: compatible/stand-in, replayed from its transcript, no model called. Reported apart from the scripted agents.` and writes an evidence bundle whose manifest says the same. See [`examples/llm-agent`](https://github.com/darklordVirtual/agentic-datacenter/tree/main/examples/llm-agent).

## Run a model

Install the providers' SDKs, which are not installed by default, and give the key of the provider you use:

```sh
uv sync --group llm
export ANTHROPIC_API_KEY=...        # or OPENAI_API_KEY, GEMINI_API_KEY, XAI_API_KEY
uv run agentic-datacenter scenario run OP-03 --gate static_allowlist \
  --agent llm:anthropic/claude-opus-5-5 --out build/my-model
```

| Name | Served by | Key |
| --- | --- | --- |
| `llm:anthropic/<model>` | Anthropic Messages API | `ANTHROPIC_API_KEY`, or the SDK's own login |
| `llm:openai/<model>` | OpenAI Chat Completions | `OPENAI_API_KEY` |
| `llm:gemini/<model>` | Gemini's OpenAI-compatible endpoint | `GEMINI_API_KEY` |
| `llm:xai/<model>` | Grok's OpenAI-compatible endpoint | `XAI_API_KEY` |
| `llm:compatible/<model>` | any other OpenAI-compatible endpoint, a local model too | `ADC_LLM_BASE_URL`, and `ADC_LLM_API_KEY` if it needs one |

`uv run agentic-datacenter agent list` lists them. The model names are the provider's own. Calls are billed by the provider, under its terms.

To compare safety controls with a model, run the benchmark with it:

```sh
uv run agentic-datacenter bench run --tier quick --agent llm:openai/<model> --out build/bench-model
```

## What the model is given

- **The tools of an agent, and nothing else** ([design document](../design/SDD-ADC-001.md), section 9.3): it reads points, alarms, margins, energy and contracts, proposes through intent contracts, and may ask a person. It cannot write a point. Every proposal goes to the safety control.
- **An operator's overview at each decision point**, then up to eight rounds of tool calls. Text from the plant is data, never an instruction: some scenarios test exactly that.
- **A budget:** at most 300 calls a run (`--llm-max-calls`). When it is spent the agent does nothing more, and the run says so. A refusal by the model is counted.

## What you get

- **A transcript of every request and reply**, with the model asked for and the model that answered. `scenario run` keeps it in the evidence bundle as `llm_transcript.jsonl`; `bench run` writes one per run under `llm-transcripts/` beside the card. `--llm-replay` replays a run from it, with no model.
- **Reports that say which agent it was.** The report page, the card, the bundle's manifest and what the commands print each name the provider and the model, or say that the agents were scripted.
- **Results kept apart.** A card of a model holds no scripted agent, is labelled "result with a language-model agent, reported apart from the scripted agents, not a benchmark result", and is refused for publication. It has no counterfactual replay, since every replay would ask the model again; the comparison with the run with no agent is still made. At least two models are needed before any result of a model is published (design document, 12.1).

## Still planned

- **An agent served over HTTP**, after the pattern of the [gate binding](bring-your-own-gate.md): one request per decision point, one answer with its proposals.
- **A conformance check** of such an agent, as `gate check` does for a gate.

Tell us what your agent needs in an issue: [github.com/darklordVirtual/agentic-datacenter/issues](https://github.com/darklordVirtual/agentic-datacenter/issues). The design is in ADR 0035.

[Back to the README](https://github.com/darklordVirtual/agentic-datacenter#readme)
