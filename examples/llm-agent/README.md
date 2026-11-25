# A recorded run of a language-model agent

`OP-03.jsonl` is the transcript of one run of `OP-03`, shortened to 900 s, under `null_gate`, seed 1, with the agent `llm:compatible/stand-in`. The agent was a scripted stand-in (`stand_in.py`), not a model: every reply in the transcript says so as its model. It shows what a run of a model gives, and that a run is replayed from its transcript with no key and no network (ADR 0035).

Replay it from the root of the repository:

```sh
uv run agentic-datacenter scenario run OP-03 --seconds 900 --agent llm:compatible/stand-in \
  --llm-replay examples/llm-agent/OP-03.jsonl --out build/llm-example
```

It prints:

```text
OP-03 null_gate (UNGOVERNED) seed 1: passed
agent: llm:compatible/stand-in. Language-model agent: compatible/stand-in, replayed from its transcript, no model called. Reported apart from the scripted agents.
evidence bundle: build/llm-example
```

`build/llm-example/manifest.json` has `"agent_kind": "language_model"`, the provider, the model and the calls, and the bundle holds the transcript as `llm_transcript.jsonl`.

To run a model of your own instead, see [Bring your agent](../../docs/guides/bring-your-own-agent.md). A change to what the agent is shown makes this transcript another run; `python examples/llm-agent/stand_in.py` records it again, and a test checks that it replays.

Under the MIT licence in `examples/LICENSE`.
