# Agentic-Datacenter

**Test AI-driven data center operations before they reach a real facility.**

A simulated data center with cooling failures, power disturbances and AI agents that propose control actions. Between the agent and the plant sits a safety control, a *gate*. Agentic-Datacenter shows what each decision does to the plant: what the gate stopped, what got through, and how often a person had to step in.

<p align="center">
  <a href="docs/media/agentic_datacenter_visual.mp4"><img src="docs/media/agentic_datacenter_visual.webp" alt="Fly-over of a rendered modular data center: the site, generator enclosures, air-cooled chillers, thermal storage and the gatehouse" width="100%"></a>
</p>
<p align="center"><sub>A rendered, illustrative facility</sub></p>

<p align="center">
  <a href="#for-data-center-operators"><strong>Operators</strong></a> ·
  <a href="#for-gate-developers"><strong>Gate developers</strong></a> ·
  <a href="#public-test"><strong>Public test</strong></a> ·
  <a href="#documentation"><strong>Documentation</strong></a>
</p>

## Try it in a minute

[![Open in GitHub Codespaces](https://github.com/codespaces/badge.svg)](https://codespaces.new/darklordVirtual/agentic-datacenter)

Or locally, with git, Python 3.12+ and [uv](https://docs.astral.sh/uv/):

```sh
git clone https://github.com/darklordVirtual/agentic-datacenter && cd agentic-datacenter
uv sync
uv run agentic-datacenter demo --scenario OP-03 --gate static_allowlist --out build/first-run
```

Open `build/first-run/index.html`: a chiller trip in a heat wave, with and without a safety control. No API keys, no external service.

## For data center operators

See what an AI agent would do to your plant before it gets near your control systems:

- **Temperatures:** what happens to IT supply air if an agent acts badly during a chiller trip, a utility loss or a leak.
- **Approvals:** which commands must never run without a person, and how often your staff would be asked.
- **Cost:** what a safety control costs in useful automation and energy.

<p align="center"><a href="docs/demo/result-report.md"><img src="docs/media/result-report.png" alt="The one-page result report of three scenarios: the plant was harmed in 1 of 3 scenarios with no safety control and in 0 of 3 with REMORA's governed execution" width="560"></a></p>

**Start here:** the [operator guide](docs/guides/operators.md) (the chiller-trip example, the scenarios and how to run them) and the [one-page result report](docs/demo/result-report.md) for decision makers.

> The facility is generic and simulated, and not calibrated against a real data center. A result shows how a decision plays out in this model, not what will happen at your site.

## For gate developers

Bring your own gate, in any language: an HTTP service, a command per decision, or a Python package. Only `ALLOW` and `DENY` are required.

```sh
export ADC_GATE_URL=http://127.0.0.1:8787  ADC_GATE_NAME=my_gate         # your service
uv run agentic-datacenter gate check http_gate                            # 1. check the connection
uv run agentic-datacenter bench run --tier quick --gate http_gate --gate static_allowlist --out build/try   # 2. a first result, in minutes
```

**Start here:** [Bring your own gate](docs/guides/bring-your-own-gate.md), step by step with an [80-line example service](examples/http-gate/server.py), and [Which way in for your project](docs/guides/which-way-in.md), for gates that score, keep state, observe only or use words of their own. How long each size of test takes, and what machine it needs, is in [Tiers](docs/bench/TIERS.md).

## Public test

[![Agentic-Datacenter public test: register your gate](docs/media/season1-register-banner.webp)](https://github.com/darklordVirtual/agentic-datacenter/issues/new?template=gate-registration.yml)

**Registration is always open.** Seasons follow one another, four weeks each, on a frozen benchmark that any gate can enter.

- **Register** with three fields. No setup is needed yet.
- **Run** the public scenarios on your own machine, whenever you are ready.
- **Hidden variants** close each season. They are drawn from a public randomness beacon at the deadline, so nobody can know them before, the authors included.

[Register your gate](https://github.com/darklordVirtual/agentic-datacenter/issues/new?template=gate-registration.yml) · [Calendar, rules and built-in gates](docs/bench/PUBLIC_TEST.md)

No benchmark result has been reported yet.

## Documentation

| | |
| --- | --- |
| **Use it** | [Operator guide](docs/guides/operators.md) · [Bring your own gate](docs/guides/bring-your-own-gate.md) · [Which way in](docs/guides/which-way-in.md) · [Command line](docs/reference/cli.md) |
| **Benchmark** | [Public test](docs/bench/PUBLIC_TEST.md) · [Tiers](docs/bench/TIERS.md) · [Fairness rules](docs/bench/FAIRNESS.md) · [Preregistration](docs/bench/PREREGISTRATION.md) · [Release check](docs/guides/release-gate.md) |
| **Reference** | [Words used here](docs/reference/glossary.md) · [Invariants](docs/reference/invariants.md) · [Design document](docs/design/SDD-ADC-001.md) · [Decisions](docs/design/adr/) |
| **Contribute** | [Calibration data](docs/calibration/contribute-data.md), for equipment makers and operators · [Contributing](CONTRIBUTING.md) |
| **Project** | [Changelog](CHANGELOG.md) · [Third-party notices](THIRD_PARTY_NOTICES.md) |

The simulated facility is generic. It is informed by how modular data centers are built and operated, and does not identify any particular facility or design document.

**Licence:** source-available under the Business Source License 1.1 ([LICENSE](LICENSE)). Development, testing, evaluation, demonstration and research are free; any other use, such as production, needs a [commercial licence](COMMERCIAL_LICENSING.md). The example gates in `examples/` are MIT, so a gate started from them is yours. The IEC 61850 package (`packages/agentic-datacenter-iec61850`) is licensed separately under GPLv3.
