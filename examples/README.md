# Examples

Two small gates and a facility to start your own from, and a recorded run of a language-model agent. Everything in this directory is under the MIT licence (`LICENSE` here), not the licence of the rest of the repository: copy it, change it and keep the result under whatever licence you choose.

| Example | What it is |
| --- | --- |
| `http-gate/server.py` | A gate served over HTTP, standard library only. The quickest way in, in any language. |
| `python-gate/` | A gate as a Python package, found by Agentic-Datacenter through an entry point. |
| `byodc/` | A facility bundle: six PODs of three kinds on the generic plant (ADR 0033). Start your own facility from it. |
| `llm-agent/` | The transcript of a run of a language-model agent, made by a scripted stand-in, that replays with no key (ADR 0035). |

The guides are [Bring your own gate](../docs/guides/bring-your-own-gate.md) and [Bring your agent](../docs/guides/bring-your-own-agent.md).
