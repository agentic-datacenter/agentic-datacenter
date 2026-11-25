# Agentic-Datacenter

Test autonomous data center operations before they reach production. A simulation-only model of a data center's operational technology, partitioned into IEC 62443 zones and conduits, in which AI-driven control decisions and the safety controls around them ("gates") can be tried, compared and benchmarked.

## Try it

[Open it in GitHub Codespaces](https://codespaces.new/darklordVirtual/agentic-datacenter), or run it on your own machine, with git, Python 3.12 or later and [uv](https://docs.astral.sh/uv/):

```sh
git clone https://github.com/darklordVirtual/agentic-datacenter && cd agentic-datacenter
uv sync
uv run agentic-datacenter demo --scenario OP-03 --gate static_allowlist --out build/first-run
```

About a minute. No API keys and no external service. Then open `build/first-run/index.html`.

## Where to start

- **[Explore the demo](demo/result-report.md):** a one-page result of three scenarios, with and without a safety control (also as a [designed page](demo/result-report.html) and the [demonstration](demo/three-scenarios.html) behind it).
- **[Bring your datacenter](guides/bring-your-own-datacenter.md):** check what fits your facility, and get one report for an operator with `facility report`. Operators also start from the [operator guide](guides/operators.md).
- **[Bring your equipment](guides/equipment.md):** use and contribute equipment models, each with its source and rights.
- **[Bring your agent](guides/bring-your-own-agent.md):** a language model as the agent, through Anthropic, OpenAI, Gemini, Grok or any OpenAI-compatible endpoint. Optional; runs use the scripted agents unless you name a model. An agent of your own served over HTTP is planned.
- **[Bring your governance](guides/bring-your-own-gate.md):** test your own safety control, then enter the [public test](bench/PUBLIC_TEST.md). Maintainers: [what you get](guides/for-governance-maintainers.md), and a workflow that keeps testing your system as this project grows.

Agentic-Datacenter never connects to real equipment, and makes no claim of IEC 62443 certification.

## What else is here

- **Design.** The [design document](design/SDD-ADC-001.md) is what the implementation followed. Decisions made since are recorded as ADRs; where they and the code differ from it, they are what holds.
- **Reference.** Generated from the code on every build: the [module registry](reference/modules.md), the [wiring of the generic profile](reference/wiring.md), the [requirement-to-test matrix](reference/requirements.md), the [command line](reference/cli.md) and the [profile schema](reference/profile_schema.md).
- **Module specs.** One per plant module, under `design/modules/`, linked from the module registry.
