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

- **Operators:** the commands above play a chiller trip in a heat wave with and without a safety control. Then read the [one-page result report](demo/result-report.md) of three scenarios (also as a [designed page](demo/result-report.html) with a chart per scenario), and the [demonstration](demo/three-scenarios.html) behind it, with every decision and its record.
- **Developers:** start with [Test your own gate](guides/bring-your-own-gate.md), then the [public test](bench/PUBLIC_TEST.md) in which gates are compared.

Agentic-Datacenter never connects to real equipment, and makes no claim of IEC 62443 certification.

## What else is here

- **Design.** The [design document](design/SDD-ADC-001.md) is what the implementation followed. Decisions made since are recorded as ADRs; where they and the code differ from it, they are what holds.
- **Reference.** Generated from the code on every build: the [module registry](reference/modules.md), the [wiring of the generic profile](reference/wiring.md), the [requirement-to-test matrix](reference/requirements.md), the [command line](reference/cli.md) and the [profile schema](reference/profile_schema.md).
- **Module specs.** One per plant module, under `design/modules/`, linked from the module registry.
