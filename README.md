# Agentic-Datacenter

**Test autonomous operations before they reach production.**

Simulate infrastructure. Evaluate decisions. Measure consequences.

<p align="center">
  <a href="docs/demo/result-report.md"><img src="docs/media/buttons/demo.svg" alt="Explore the demo: view a simulated result" width="320" height="52"></a>
</p>

<p align="center">
  <a href="docs/guides/bring-your-own-datacenter.md"><img src="docs/media/buttons/datacenter.svg" alt="Bring your datacenter: check your facility" width="280" height="58"></a>
  <a href="equipment/README.md"><img src="docs/media/buttons/equipment.svg" alt="Bring your equipment: use and contribute models" width="280" height="58"></a>
</p>
<p align="center">
  <a href="docs/guides/bring-your-own-agent.md"><img src="docs/media/buttons/agent.svg" alt="Bring your agent: a language model as the agent, optional" width="280" height="58"></a>
  <a href="docs/guides/bring-your-own-gate.md"><img src="docs/media/buttons/governance.svg" alt="Bring your governance: test your safety controls" width="280" height="58"></a>
</p>

<p align="center">
  <a href="docs/media/agentic_datacenter_visual.mp4"><img src="docs/media/agentic_datacenter_visual.webp" alt="Illustrative rendered modular data center, with cooling, power and IT infrastructure" width="100%"></a>
</p>
<p align="center"><sub>Illustrative facility · <a href="docs/media/agentic_datacenter_visual.mp4">View video</a></sub></p>

Text links: [Explore the demo](docs/demo/result-report.md) · [Bring your datacenter](docs/guides/bring-your-own-datacenter.md) · [Bring your equipment](equipment/README.md) · [Bring your agent](docs/guides/bring-your-own-agent.md) · [Bring your governance](docs/guides/bring-your-own-gate.md)

## What you can discover

See how an AI agent's decisions affect temperatures, IT load, energy and human approvals, and replay every blocked command as if it had run. In a development run with scripted agents, the simulated plant was harmed in 1 of 3 scenarios without a safety control and 0 of 3 with REMORA's governed execution. [Inspect the result, its method and its limits](docs/demo/result-report.md). This is not a benchmark result, and not proof of production safety.

## Try it locally

Requires Git and [uv](https://docs.astral.sh/uv/) with Python 3.12 or later. Or [open it in GitHub Codespaces](https://codespaces.new/darklordVirtual/agentic-datacenter).

```sh
git clone https://github.com/darklordVirtual/agentic-datacenter && cd agentic-datacenter
uv sync
uv run agentic-datacenter demo --scenario OP-03 --gate static_allowlist --out build/first-run
```

Open `build/first-run/index.html` to see the chiller trip play out with and without the built-in safety control. The first install downloads dependencies. The simulator needs no API key.

For a facility report, follow the [operator quickstart](docs/guides/bring-your-own-datacenter.md#try-the-example).

## Participate

[How the benchmark works](docs/bench/HOW-IT-WORKS.md) · [Public benchmark](docs/bench/PUBLIC_TEST.md) · [Register a gate](https://github.com/darklordVirtual/agentic-datacenter/issues/new?template=gate-registration.yml) · [Contribute measured data](docs/calibration/contribute-data.md) · [Contributing](CONTRIBUTING.md)

Registration is always open. Public tests use frozen versions, and results on a facility of your own are never ranked as benchmark results. See [fairness](docs/bench/FAIRNESS.md) and [release checks](docs/guides/release-gate.md).

## Documentation

[Operator guide](docs/guides/operators.md) · [Which way in](docs/guides/which-way-in.md) · [Command line](docs/reference/cli.md) · [Design](docs/design/SDD-ADC-001.md) · [Decisions](docs/design/adr/) · [Changelog](CHANGELOG.md) · [Security](SECURITY.md)

## Trust and licensing

Simulation only: nothing connects to real equipment. The reference facility is generic and not calibrated against a real data center, and a result shows how a decision plays out in this model, not at your site. Sources and their limits are in the [third-party notices](THIRD_PARTY_NOTICES.md).

Source-available under the [Business Source License 1.1](LICENSE): development, testing, evaluation, demonstration and research are free. Production use needs a [commercial licence](COMMERCIAL_LICENSING.md), which also says what is offered under agreement. The examples are MIT, the IEC 61850 package is GPLv3, and each registry entry keeps the terms of its source. Commercial agreements never buy a benchmark result.
