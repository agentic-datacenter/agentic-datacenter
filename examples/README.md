# Examples

Small gate examples and a facility to start your own from. Everything in this directory is under the MIT licence (`LICENSE` here), not the licence of the rest of the repository: copy it, change it and keep the result under whatever licence you choose.

| Example | What it is |
| --- | --- |
| `command-gate/adapter.py` | A local JSON-in/JSON-out gate, standard library only. Start here for a first run without an HTTP service. |
| `http-gate/server.py` | An HTTP gate, standard library only. Use this when you need a long-lived service. |
| `python-gate/` | A gate as a Python package, found by Agentic-Datacenter through an entry point. |
| `byodc/` | A facility bundle: six PODs of three kinds on the generic plant (ADR 0033). Start your own facility from it. |

Start with the [local quickstart](../docs/guides/which-way-in.md#try-a-local-adapter) or see [Bring your own gate](../docs/guides/bring-your-own-gate.md) for the full interface.
