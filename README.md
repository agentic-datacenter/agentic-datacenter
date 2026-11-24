# Agentic-Datacenter

**Independent validation of autonomous AI operations in a data center, before they reach a real one.**

Put an AI agent, a safety control and a facility together in a simulated plant. Agentic-Datacenter shows what each decision does to temperatures, IT load, energy and approvals. For every command that was stopped, it plays the same moment again as if the command had run, so a block that avoided harm is told from a block that only cost a useful step.

<p align="center">
  <a href="docs/media/agentic_datacenter_visual.mp4"><img src="docs/media/agentic_datacenter_visual.webp" alt="Fly-over of a rendered modular data center: the site, generator enclosures, air-cooled chillers, thermal storage and the gatehouse" width="100%"></a>
</p>
<p align="center"><sub>A rendered, illustrative facility</sub></p>

## See it in one minute

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/darklordVirtual/agentic-datacenter)

Or locally, with git, Python 3.12+ and [uv](https://docs.astral.sh/uv/):

```sh
git clone https://github.com/darklordVirtual/agentic-datacenter && cd agentic-datacenter
uv sync
uv run agentic-datacenter demo --scenario OP-03 --gate static_allowlist --out build/first-run
```

Open `build/first-run/index.html`. It shows a chiller trip in a heat wave, with and without a safety control. No API keys and no external service are needed.

**What a result looks like.** The [one-page report](docs/demo/result-report.md) of three scenarios, a development run with scripted agents and REMORA's governed execution as the safety control:

| | No safety control | With the safety control |
| --- | ---: | ---: |
| Scenarios in which the plant was harmed | 1 of 3 | 0 of 3 |
| Agent commands stopped | 15 of 69 | 40 of 69 |
| … of those, replayed: would have done harm | | 3 |
| … of those, replayed: would have been a useful step | | 0 |
| Times a person was asked | 0 | 1 |

<p align="center"><a href="docs/demo/result-report.md"><img src="docs/media/result-report.png" alt="The one-page result report of three scenarios: the plant was harmed in 1 of 3 scenarios with no safety control and in 0 of 3 with REMORA's governed execution" width="560"></a></p>

## What you bring, and what you get back

| You are | You bring | You get back, at once | Start here |
| --- | --- | --- | --- |
| **A data center operator** | Your facility, as a directory of files | A report of which scenarios and controls fit your site, and runs of every gate on it. You see which commands must never run without a person, and how often your staff would be asked | [Bring your own data center](docs/guides/bring-your-own-datacenter.md) |
| **An equipment maker** | A model of your equipment: values, sources, rated conditions | Your equipment in every facility that names it, with its tier on every card that uses it | [The equipment registry](equipment/README.md) |
| **A developer of a gate or a governance system** | A gate: a Python package, an HTTP service in any language, or a command | A result card in minutes, against 27 scenarios and two scripted agents, and a place in the public test | [Bring your own gate](docs/guides/bring-your-own-gate.md) |
| **An operator with measured data** | Weather or plant series, with their licence | Simulations of your own conditions, and calibrated models for everyone | [Calibration data](docs/calibration/contribute-data.md) |
| **A researcher** | A question about agents, safety controls or plant behaviour | Runs that anyone can repeat: deterministic, frozen versions, every result traced to its commit | [Design document](docs/design/SDD-ADC-001.md) |

Agents and scenarios of your own are planned. Today the agents are scripted and the scenarios come from the library (`docs/guides/which-way-in.md`).

## Free, and under agreement

Everything needed to try, evaluate and research is free. What a business runs on, and what is made for one customer, is under a commercial agreement.

| Free under the [Business Source License](LICENSE) | Under a [commercial agreement](COMMERCIAL_LICENSING.md) |
| --- | --- |
| The simulator, the scenarios, the contracts and the benchmark method | Use in production, and inside a product or service |
| The formats: facility bundles, equipment entries, the gate wire format | Private facility environments, kept and run for one operator |
| The public equipment entries, each with its source and licence | Calibrated models of a customer's own equipment and site |
| `facility check` and runs on your own facility, for evaluation | Regression testing on every change: a new agent version, a policy, firmware, a topology |
| The public test, and every public result card | Private evidence reports, for approval of autonomous operation, an insurer or a due diligence |
| The example gates and facilities, under MIT, yours to keep | Large runs on the benchmark runner, and support |

A commercial agreement never buys a result. Rankings, seasons and the gate of the equipment registry are the same for everyone (see the rules below).

## Why every contribution is worth more than itself

Each contribution makes the others more useful:

- **An equipment model** is used in every facility that names it.
- **A facility** is a new place where every gate and every equipment model is tested.
- **A gate** is a new answer that every operator can compare.
- **A scenario** tests every gate, on every facility it fits.
- **A dataset** calibrates the models that every facility uses.

What builds up over time does not lie in the code. It lies in what the code has made, recorded so that it can be checked:

- every frozen benchmark version and every season;
- every result card, each traced to its commit and signed on the benchmark runner;
- every registry entry, each with its source, its licence and the rights to use it.

## Rules that keep it fair

- **Results are never bought.** A maker can have its equipment model checked. That changes the model's tier, never a ranking, and no card is ranked by tier.
- **Every value says where it came from.** A value carries its source or is marked as assumed, and the card counts both. An equipment entry without a recorded right to use and redistribute it does not enter the registry.
- **Your facility is yours.** A card from your own facility is labelled as such and is never published as a benchmark result.
- **Simulation only.** Nothing connects to real equipment.

## Public test

[![Agentic-Datacenter public test: register your gate](docs/media/season1-register-banner.webp)](https://github.com/darklordVirtual/agentic-datacenter/issues/new?template=gate-registration.yml)

**Registration is always open.** Seasons follow one another, four weeks each, on a frozen benchmark that any gate can enter. Register with three fields, then run the public scenarios on your own machine. Hidden variants, drawn from a public randomness beacon at each deadline, close every season.

A result is *verified* when the maintainers ran it from the frozen tag on their benchmark runner. It is *self-reported* when a participant ran it. No benchmark result has been reported yet.

[Register your gate](https://github.com/darklordVirtual/agentic-datacenter/issues/new?template=gate-registration.yml) · [Calendar, rules and built-in gates](docs/bench/PUBLIC_TEST.md)

## Documentation

| | |
| --- | --- |
| **Use it** | [Operator guide](docs/guides/operators.md) · [Bring your own data center](docs/guides/bring-your-own-datacenter.md) · [Bring your own gate](docs/guides/bring-your-own-gate.md) · [Which way in](docs/guides/which-way-in.md) · [Command line](docs/reference/cli.md) |
| **Equipment** | [Registry](equipment/README.md) · [How entries are made and checked](docs/design/adr/0034-equipment-registry.md) |
| **Benchmark** | [Public test](docs/bench/PUBLIC_TEST.md) · [Tiers](docs/bench/TIERS.md) · [Fairness rules](docs/bench/FAIRNESS.md) · [Preregistration](docs/bench/PREREGISTRATION.md) · [Release check](docs/guides/release-gate.md) |
| **Reference** | [Words used here](docs/reference/glossary.md) · [Invariants](docs/reference/invariants.md) · [Design document](docs/design/SDD-ADC-001.md) · [Decisions](docs/design/adr/) |
| **Project** | [Contributing](CONTRIBUTING.md) · [Changelog](CHANGELOG.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) · [Commercial licence](COMMERCIAL_LICENSING.md) |

The simulated facility is generic and not calibrated against a real data center. A result shows how a decision plays out in this model, not what will happen at your site. The generic facility was informed by an unpublished construction specification for a modular data center, which the repository does not identify or quote and takes no values from ([notices](THIRD_PARTY_NOTICES.md)).

**Licence:** source-available under the Business Source License 1.1 ([LICENSE](LICENSE)). Development, testing, evaluation, demonstration and research are free. Any other use, such as production, needs a [commercial licence](COMMERCIAL_LICENSING.md). The examples in `examples/` are MIT, so a gate or a facility started from them is yours. The IEC 61850 package (`packages/agentic-datacenter-iec61850`) is licensed separately under GPLv3. Each registry entry keeps the terms of its source (`equipment/licences/`).
