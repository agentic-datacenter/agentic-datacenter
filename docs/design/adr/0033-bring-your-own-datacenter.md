# ADR 0033: Bring your own data center

- **Status:** Accepted on 2026-11-24. The owner asked for the feature to be built.
- **Date:** 2026-11-24
- **SDD:** 3, 5, 5.3, 9.4, 10, 11, 12.1, 13; ADR 0018, 0029; `docs/design/ot-iac-import-and-scenario-coverage-proposal.md`; new requirements `ADC-FAC-001` to `ADC-FAC-010`

## Context

The facility is a profile (SDD 3), and changing the facility is meant to mean changing a profile, never the code. That holds for counts that are key sets, such as the number of PODs and trains. It holds for little else. A survey of the code on 2026-11-24 found these gaps.

**What already works.**

- Instances and wiring come from `key_sets`, `tables`, `for_each` and `with`.
- Fuel, life safety, the MV feeders, the benign agent and the train count of the supervisory overview follow the key sets.
- The oracle sums harm over every instance it finds.
- The zone of an instance comes from its manifest pattern.
- Per-instance parameters are possible, but only by listing the same module in several `modules:` entries with disjoint instances.

**What does not work.**

1. **Parameters.**
   - Parameters belong to a module use, not to an instance, and `Profile.with_param` changes every use of a module.
   - A misspelt parameter is silently ignored, and the default is used in its place.
   - A value carries `source` or `assumed`, and nothing more: no maker, model or evidence.
2. **One file.** A facility is one YAML file. An operator's description of a real site is many: electrical, cooling, PODs, equipment. These are assembled from exports of tools that know nothing of this format.
3. **Contracts.** The contract library names single instances (`CHW`, `TES-1`, `PHPS`). It is checked as a whole against the plant (`ContractLibrary.check_against`), and one missing tag refuses all of it. A facility without a `TES-1` cannot run a single scenario.
4. **Scenarios.** Scenarios name generic instances in their events: `cooling.chw_plant[CHW]`, `cooling.pod[07]`, `electrical.utility[INC-2]`. They have no notion of the facility they need.
5. **Cards.** A card names the facility only by the hash of its profile. Nothing says that a card is from someone's own facility, or how much of it rests on assumed values.
6. **Counts in the code.** Three chillers, three pumps, two incomers and six zone sensors per POD are fixed in code, ports and points.

## Decisions

### 1. A facility bundle

A facility can be a directory, the *bundle*, with `datacenter.yaml` at its root:

```yaml
schema_version: 2
name: example_colo
site: DC7
description: ...
include: [topology/electrical.yaml, topology/cooling.yaml, pods/*.yaml, equipment/*.yaml]
```

Each included file is a mapping with any of the keys of a profile that hold facility data: `key_sets`, `tables`, `modules`, `connections`, `equipment` and `economics`.

- **Merging.** Lists are joined in the order of `include`, files of one pattern in name order. Mappings are merged, and a key defined twice is refused, naming both files.
- **Safety.** A bundle is offline, explicitly supplied data:
  - only `yaml.safe_load`;
  - no path outside the bundle directory, after symbolic links are resolved;
  - at most 256 files of at most 1 MiB each;
  - no network and nothing executed.
- **Lowering.** `agentic_datacenter.core.facility` compiles a bundle into an ordinary schema-1 profile. A module use whose instances have different parameters is split into one use per distinct set. Everything downstream, from the registry to the oracle, sees a schema-1 profile.
- **What a run records.** The profile hash is the facility's hash. The bundle's file hashes are kept beside it.
- **Schema-1 profiles are unchanged.** They are read as before and their hash is unchanged. `generic_dc.yaml` keeps the hash frozen in `docs/bench/VERSION.json`.

### 2. Values per instance, from equipment models

A module use may name an equipment model and give overrides per instance:

```yaml
modules:
  - id: cooling.pod
    for_each: pods
    instance: "{pods}"
    equipment: pod_air_150
    overrides:
      "01": {equipment: pod_air_300}
      "02": {params: {fan_kw: {value: 9.0, unit: kW, source: "site survey 2026-10"}}}
equipment:
  pod_air_300:
    module: cooling.pod
    maker: Example Cooling
    model: AHU-4x75
    evidence: datasheet rev C
    params:
      design_it_kw: {value: 300.0, unit: kW, source: "datasheet rev C, table 2"}
```

- **Precedence:** the module's default, then the equipment model, then the use's `params`, then the instance's override.
- **Provenance.** Every resolved value keeps its provenance. A value from an equipment model is sourced as `equipment <id>: <its source>`.
- **One module per model.** An equipment model belongs to one module, and a use of it by another module is refused.
- **Sensitivity runs.** `Profile.with_param` takes an optional instance and changes only that instance.

This gives heterogeneous PODs: an AI POD, an enterprise POD and a storage POD with different load, airflow, thermal mass and AHU counts, side by side.

### 3. A parameter no module reads is refused

When the registry builds an instance, it hands the module its parameters through a mapping that records which names the module reads, whether by `get`, by index or by iteration. A name the module did not read while it was built is refused, with the module and the names it did read. A misspelt `desing_kw` therefore stops the build instead of leaving the default in place.

The check reads what the code does, so there is no list to keep in step with it. A stub is not checked, because a stub reads fewer parameters than its module by design.

### 4. `facility check`

`agentic-datacenter facility check <bundle>` does the following:

1. Compiles the bundle, validates it and builds the plant.
2. Runs the design point for five simulated minutes and reports whether every bus balances.
3. Writes a report, as JSON and Markdown, of what applies to this facility:
   - each contract of the library, as loaded, or as not loaded with the first tag it lacks;
   - each scenario, as runnable, or as not runnable with what it needs;
   - the resolved parameters, counted by provenance (`source`, `measured`, `assumed`).

`agentic-datacenter facility compile <bundle> --out <file>` writes the lowered profile, so it can be read and diffed.

### 5. On a facility of one's own, what does not fit is listed, not refused

The commands that run scenarios, `scenario run`, `bench run`, `demo` and `whatif run`, take `--facility <bundle or profile>` beside `--profile`.

- **Contracts.** Under `--facility`, a contract that does not fit the plant is not loaded. It is listed with its reason, and the others are loaded. Under `--profile`, the library is checked as a whole, as before, so a broken contract still fails loudly in the benchmark.
- **Scenarios.** Under `--facility`, a scenario that names an instance, a key or a zone the facility lacks is not run. It is listed as "not run: needs …" and counted in the card's denominator, never skipped silently.
- **Agents.** A scripted agent that proposes through a contract that is not loaded is refused for an unknown contract. The card counts such proposals.

This is the same rule as the plant map of ADR 0029 (`ADC-PLT-004`), on the built-in plant. The code that decides it serves both.

### 6. What a card from one's own facility may claim

A run under `--facility` gives a card with a `facility` block. The block holds:

- the name, site and description;
- the profile hash and the bundle's file hashes;
- the equipment models used, with maker, model and evidence;
- the counts of resolved values by provenance;
- the contracts not loaded and the scenarios not run.

`benchmark_version.frozen` is false. The label is "result on a facility of its owner, not a benchmark result", and `bench check --publication` refuses the card. A card is never ranked beside a frozen version. A card without `--facility` has no `facility` block and is unchanged, byte for byte.

### 7. Counts that are fixed in code

The number of chillers and pumps becomes a module parameter, as `ahu_count` already is. The points and ports of a fourth or later unit are generated from the count. With the count at three, every tag, port and state hash is the one it was. The supervisory overview reads the counts and the required number of units from the plant, not from the code. Two incomers and six zone sensors stay fixed in this ADR, and the facility report says so.

### 8. Not in this ADR

- **Importers.** NetBox or other DCIM tools, Terraform, Kubernetes, IFC, OPC UA NodeSet, IEC 61850 SCL and Redfish. The bundle is the target an importer writes, and each importer is its own ADR. An importer must keep the line the proposal draws between what an export says and what was assumed.
- **New physics:** liquid cooling (CDU, direct-to-chip), storage and network loads, economics beyond energy. Each is a new module with its own spec, at fidelity F0 or F1.
- **Measured IT load series.** ADR 0018 reads weather only. An IT-load column is its own decision.
- **Oracle limits per facility.** The oracle keeps 27 °C and 32 °C, and the card states them (ADR 0029, open question 7).
- **An equipment registry run as a service.** Equipment models are files in the bundle.

## Requirements

| ID | Requirement | PR |
| --- | --- | --- |
| `ADC-FAC-001` | A bundle compiles to one schema-1 profile. The same files give the same profile and hash. Each input file's SHA-256 is recorded. A path outside the bundle, a missing include, a key defined twice, too many files or too large a file is refused. | 1 |
| `ADC-FAC-002` | A schema-1 profile reads as before and keeps its hash. `generic_dc.yaml` has the hash frozen in `docs/bench/VERSION.json`. | 1 |
| `ADC-FAC-003` | Parameters resolve per instance: default, equipment model, use, instance override. Each resolved value keeps its provenance, and `with_param` can change one instance. | 1 |
| `ADC-FAC-004` | Building an instance refuses a parameter its module did not read, naming the module. A stub is not checked. | 1 |
| `ADC-FAC-005` | An equipment model names its module, maker, model and evidence, and a use by another module is refused. | 1 |
| `ADC-FAC-006` | `facility check` builds the plant of a bundle, runs the design point and reports the contracts and scenarios that apply, each that does not with its reason, and the resolved values by provenance. | 2 |
| `ADC-FAC-007` | Under `--facility`, a contract that does not fit is not loaded and is listed. Under `--profile`, the library is refused as a whole as before. | 2 |
| `ADC-FAC-008` | Under `--facility`, a scenario that names an instance, key or zone the facility lacks is not run, and is listed and counted. | 2 |
| `ADC-FAC-009` | A card under `--facility` carries the `facility` block, is never a benchmark result and is refused for publication. A card without it is unchanged. | 2 |
| `ADC-FAC-010` | Chillers and pumps are counted by a parameter. At three, every tag, port and state hash is unchanged, and the overview reads counts and required units from the plant. | 3 |

The pull requests are: (1) bundle, equipment and declared parameters; (2) `facility check`, `--facility` runs and cards; (3) counts of chillers and pumps. An example bundle with three kinds of POD and the guide `docs/guides/bring-your-own-datacenter.md` come with (2).

## Consequences

- An operator can describe their own facility in files they can keep beside their own exports, and run every scenario that fits it. They are told plainly which scenarios and contracts do not fit, and how much of the facility rests on assumed values.
- Every number on such a card is a result of this simulator on that description. It is not a statement about the real site, and the card says so.
- Misspelt parameters, which today change nothing silently, are refused. A profile from another project that sets an undeclared parameter of a built-in module stops loading until it is corrected.
- The benchmark is untouched. `generic_dc.yaml`, the contract library, the scenarios and the frozen version keep their hashes, and bench runs keep refusing a library that does not fit.
