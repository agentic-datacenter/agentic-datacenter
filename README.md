# Agentic-Datacenter

**A test bench for the governance gates that stand between AI operations agents and critical infrastructure.**

Agentic-Datacenter simulates the control systems of a data center: power, cooling, fuel, fire safety and physical security. An AI agent proposes changes to the plant. A governance gate decides whether each change may happen. Agentic-Datacenter then executes what was allowed, and measures what the gate let through and what it blocked without need. Any project's gate can sit in that seat and is judged on the same scenarios, agents and seeds as every other.

<p align="center">
  <a href="docs/media/agentic_datacenter_visual.mp4"><img src="docs/media/agentic_datacenter_visual.webp" alt="Fly-over of a rendered modular data center: the site, generator enclosures, air-cooled chillers, thermal storage and the gatehouse" width="100%"></a>
</p>
<p align="center"><sub>A rendered, illustrative facility</sub></p>

## Test your gate

Your gate does not have to live in this repository or be written in Python. The quickest way in is a small HTTP service, in any language, that answers one question: may this proposal go ahead?

Not a gate in that sense, for example a project that keeps budgets, gives scores, only observes, or signs receipts? [Which way in for your project](docs/guides/which-way-in.md) has one row per kind of project. Each row says how to connect it, what is measured, and what is not there yet.

**You need** git, Python 3.12 or later and [uv](https://docs.astral.sh/uv/).

**1. Get Agentic-Datacenter.**

```sh
git clone https://github.com/darklordVirtual/agentic-datacenter && cd agentic-datacenter
uv sync
```

**2. Serve your gate.** For each proposal Agentic-Datacenter sends `POST /evaluate` with the facts it read from the simulated plant (never the agent's own word). You answer with a verdict and your reasons:

| Verdict | Meaning |
| --- | --- |
| `ALLOW` | Execute exactly this change, once, within 30 simulated seconds. |
| `DENY` | Do not execute. |
| `VERIFY` | A person must approve it first. |
| `ABSTAIN` | The evidence is missing, stale or contradictory. Nothing is executed. |

Only `ALLOW` and `DENY` are required. A gate that knows nothing else answers with those two, passes the check and is scored like any other gate. Your own words work too: `permit`, `block`, `ask`, `require_approval`, `skip` and others are read as the verdict they mean. The rules that keep gates with different verdicts comparable are in [docs/bench/FAIRNESS.md](docs/bench/FAIRNESS.md).

Afterwards Agentic-Datacenter tells you on `POST /outcome` what became of the decision. The message format is [`agentic_datacenter.gate.http/1`](docs/reference/gate-http-v1.schema.json). For a working service to copy, see [examples/http-gate/server.py](examples/http-gate/server.py) (standard-library Python, about 80 lines).

**3. Check that Agentic-Datacenter can talk to it.**

```sh
export ADC_GATE_URL=http://127.0.0.1:8787   # where your service listens
export ADC_GATE_NAME=my_gate                # the name shown in results
uv run agentic-datacenter gate check http_gate
```

**4. Run it against a built-in gate.** Choose a tier ([docs/bench/TIERS.md](docs/bench/TIERS.md)):

```sh
uv run agentic-datacenter bench run --tier quick --gate http_gate --gate static_allowlist --allow-unfrozen --jobs 4 --out build/quick
uv run agentic-datacenter bench run --tier standard --gate http_gate --gate static_allowlist --allow-unfrozen --jobs 4 --out build/bench
uv run agentic-datacenter bench check build/bench/result_card.json --gate http_gate
```

`quick` runs every scenario, shortened, once, in about half an hour of processor time, less with `--jobs`. It is for trying your gate. `standard` runs every scenario at full length with three seeds. That takes an estimated hour or so on eight cores. `season` is the 30 seeds a public-test season reports, and it can be split over machines and merged. `--scenario AD-03 --seconds 900` gives a first look in about a minute.

A gate that runs as a hook rather than a service is attached as `command_gate`, with `ADC_GATE_COMMAND` set to the command to run per decision. Gates written in Python can be installed as a package instead. The template is [examples/python-gate](examples/python-gate). Every step is in the [full guide](docs/guides/bring-your-own-gate.md).

## Participating gates

| Gate | Project | Attached as | Operating profile | Written by Agentic-Datacenter's authors | Result |
| --- | --- | --- | --- | --- | --- |
| `null_gate` | Agentic-Datacenter baseline: no gate | built in | `UNGOVERNED` | yes | development runs only |
| `static_allowlist` | Agentic-Datacenter baseline: role and range checks | built in | `STATIC_ALLOWLIST` | yes | development runs only |
| `remora` | REMORA, decision service | built in, [pinned](REMORA_PIN) | `DECISION_ONLY` | yes | development runs only |
| `remora_governed` | REMORA, execution service | built in, [pinned](REMORA_PIN) | `GOVERNED` | yes | development runs only |
| `remora_shadow` | REMORA, shadow | built in, [pinned](REMORA_PIN) | `SHADOW` | yes | development runs only |
| *your gate* | | HTTP or Python package | | | register with the "Gate registration" issue form |

A row is added when a gate is registered. Its result is filled in from a result card that passed `agentic-datacenter bench check`, with a link to the "Gate result" issue that carries the card. Results of gates written by Agentic-Datacenter's authors are reported apart from the rest.

## Public test

The public test runs in seasons ([docs/bench/PUBLIC_TEST.md](docs/bench/PUBLIC_TEST.md)). Each season freezes one version of the benchmark. Part of the scenarios are hidden variants, drawn from a public randomness beacon at a date announced in advance. Nobody can know them before that date, Agentic-Datacenter's authors included, so no gate can be tuned to them. Gates are registered with their exact version before the date. Anyone can reproduce a result: the same version, gate and seeds give the same result card, byte for byte, on any machine.

**Status:** season 1 is being prepared. No benchmark result has been reported. The benchmark version is not frozen, and every run so far is a development run and labelled as one. The hypotheses and the analysis plan are fixed in advance in [docs/bench/PREREGISTRATION.md](docs/bench/PREREGISTRATION.md).

## Words used here

| Term | Meaning |
| --- | --- |
| Gate | The system under test. It decides on each proposal. It never writes to the plant itself. |
| Operating profile | What a gate is allowed to do: decide only (`DECISION_ONLY`), decide and execute (`GOVERNED`), watch only (`SHADOW`), and so on. Results are always shown beside the profile. |
| Counterfactual replay | For each blocked proposal, Agentic-Datacenter replays the run as if it had been allowed. This shows whether the block prevented harm or was a false block. |
| Result card | The JSON file a benchmark writes: safety, false blocks and approvals per gate and agent. |
| `agentic-datacenter bench check` | Refuses a result card in which harm got through, or that is incomplete. |
| Development run | Any run made with `--allow-unfrozen`. It cannot be reported as a benchmark result. |

## Other things to run

```sh
uv sync --all-groups                 # also installs REMORA and the IEC 61850 server (Linux wheels only)
uv run agentic-datacenter demo                    # three scenarios with and without a gate; writes build/demo/index.html
uv run agentic-datacenter scenario run OP-03 --gate remora_governed --agent scripted_adversarial   # evidence in build/evidence/
uv run agentic-datacenter scenario verify build/evidence
uv run agentic-datacenter gate list
```

The benchmark uses two scripted agents, one careful (`scripted_benign`) and one hostile (`scripted_adversarial`). `agentic-datacenter scenario run` also takes `scripted_drift` and `scripted_flood`. Other commands: `agentic-datacenter whatif`, `agentic-datacenter modules`, `agentic-datacenter profile`, `agentic-datacenter run`, `agentic-datacenter contracts compile`, `agentic-datacenter scl export` and `agentic-datacenter data`.

## What is in it

- Sixteen plant modules. They give plausible behaviour, but none has been calibrated against a real facility.
- IEC 62443 zones and conduits.
- Simulated Modbus/TCP, OPC UA, SNMP, BACnet/IP and IEC 61850 MMS servers.
- Twenty-three scenarios, operational and adversarial, with an evidence bundle per run.
- The benchmark with its hidden variants, and the result card check.

The code is ten Python packages under `packages/` with one `uv` lock. The layer rules between them are checked by `uv run --all-groups lint-imports`.

## Read more

- [docs/guides/bring-your-own-gate.md](docs/guides/bring-your-own-gate.md): connect a gate, step by step.
- [docs/design/SDD-ADC-001.md](docs/design/SDD-ADC-001.md): the design document. Its opening table says which sections to read for your role.
- [docs/design/zone_model.md](docs/design/zone_model.md), [docs/design/threat_model.md](docs/design/threat_model.md) and the decisions in [docs/design/adr/](docs/design/adr/).
- [docs/guides/release-gate.md](docs/guides/release-gate.md): what makes `agentic-datacenter bench check` refuse a card.
- [CONTRIBUTING.md](CONTRIBUTING.md): rules for changes to Agentic-Datacenter itself.
- The simulated facility is generic. It was informed by an unpublished construction specification, which nothing in this repository identifies or quotes; see [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
- Licence: Business Source License 1.1, see [LICENSE](LICENSE); `packages/agentic-datacenter-iec61850` is GPLv3.
