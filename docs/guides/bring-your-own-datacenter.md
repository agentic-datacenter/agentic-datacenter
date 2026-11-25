# Bring your own data center

Describe your own facility in a directory of files, check what of the scenarios and contracts fits it, and run gates and agents on it. Everything stays on your machine. Nothing in a bundle is executed, and nothing connects to real equipment (ADR 0033).

```sh
uv run agentic-datacenter facility check examples/byodc          # what fits, and a five-minute run
uv run agentic-datacenter bench run --facility examples/byodc --tier quick --gate static_allowlist
```

The example is six PODs of three kinds on the generic electrical and cooling plant. Its values are illustrative.

| PODs | Kind | IT load (kW) |
| --- | --- | --- |
| 01, 02 | AI training | 300 |
| 03, 04 | Enterprise | 150 |
| 05, 06 | Storage | 80 |

## A bundle

```text
my-dc/
├── datacenter.yaml        # name, site, what to include; key sets and tables may live here
├── topology/*.yaml        # modules and connections: power, cooling
├── pods/*.yaml            # the POD modules, each with its own equipment model if you like
└── equipment/*.yaml       # equipment models: maker, model, evidence and values
```

`datacenter.yaml`:

```yaml
schema_version: 2
name: my_dc
site: DC7
include: ["topology/*.yaml", "pods/*.yaml", "equipment/*.yaml"]
```

An included file holds any of `key_sets`, `tables`, `modules`, `connections`, `equipment` and `economics`.

- **Merging.** Lists are joined in the order of `include`. A name defined in two files is refused, with both files named.
- **Limits.** A bundle holds at most 256 files of at most 1 MiB each, and no path may lead outside it.

## Values per POD and equipment models

A module use names an equipment model, and an instance may name another, or give values of its own:

```yaml
modules:
  - id: cooling.pod
    for_each: pods
    instance: "{pods}"
    equipment: pod_enterprise
    overrides:
      "01": {equipment: pod_ai}
      "05": {params: {fan_kw: {value: 3.5, unit: kW, source: "site survey 2026-10"}}}
equipment:
  pod_ai:
    module: cooling.pod
    maker: Example
    model: AI air handling
    evidence: datasheet rev C
    params:
      design_it_kw: {value: 300.0, unit: kW, source: "datasheet rev C, table 2"}
```

- **Precedence.** The module's default comes first, then the equipment model, then the use's values, then the instance's override. The last one wins.
- **Provenance.** Every value carries `source` or `assumed: true`. The card counts how many of each your facility rests on.
- **Misspellings.** A parameter the module does not read is refused when the plant is built, so a misspelt name never leaves the default in place silently.

## What fits

`facility check` writes `facility_report.md` and `facility_report.json`:

- the IT load served against design, the power at the incomers and the hottest supply air, after five minutes with no agent;
- the contracts that load, and those that do not, with the first point or kind of equipment each lacks;
- the scenarios that fit, and those that do not, with what each needs. `OP-06` needs a POD 07, for example;
- what cannot be varied yet: three pumps in the pump station, two utility incomers per MV switchgear, six zone sensors per POD, and the oracle's limits of 27 °C and 32 °C. The number of chillers can be varied: `chillers`, 1 to 9, on `cooling.chw_plant`.

## Results on your facility

`bench run --facility` and `scenario run --facility` run only what fits. The card has a `facility` block:

- the name, the site and the profile hash;
- the SHA-256 of every file in the bundle;
- the equipment models used;
- the values counted by provenance;
- the contracts not loaded and the scenarios not run.

The card is labelled "result on a facility of its owner, not a benchmark result", and `bench check --publication` refuses it. It shows what each gate did on your description of your facility. It says nothing about the real site.

## Licence

The example bundle in `examples/byodc/` is under the MIT licence, like the other examples. A bundle of your own is yours.
