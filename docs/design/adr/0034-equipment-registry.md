# ADR 0034: An equipment registry from open sources, with the rights to every value recorded

- **Status:** Accepted on 2026-11-24. The owner asked for the registry to be built.
- **Date:** 2026-11-24
- **SDD:** 2, 5, 11; ADR 0025, 0031; requirements `ADC-PRV-005`, new `ADC-EQP-001` to `ADC-EQP-004`

## Context

ADR 0033 lets a facility name equipment models. A model written by its owner is as good as the owner's data. Much useful data is public, but public is not the same as free to redistribute. The project's own rule (`ADC-PRV-005`) is that every source and its terms are recorded.

Read on 2026-11-24, each at the commit named:

| Source | What it holds | Terms as read |
| --- | --- | --- |
| Modelica Buildings Library, `lbl-srg/modelica-buildings` at `e79800b7…` | 160 chiller performance records in `Buildings/Fluid/Chillers/Data/ElectricEIR.mo`, 159 of them named after a maker and model and generated from EnergyPlus `Chiller:Electric:EIR` objects | A revised 3-clause BSD licence with an added paragraph on enhancements (`Buildings/UsersGuide/License.mo`). No SPDX identifier is stated. The names of the Modelica Association, IBPSA, the University of California, LBNL and the U.S. Dept. of Energy may not be used to endorse or promote a derived product |
| NetBox device-type library, `netbox-community/devicetype-library` at `2648bfb4…` | Device types with maker, model, rack units and power ports, `maximum_draw` and `allocated_draw` | CC0-1.0. Trademark and patent rights are not waived. The unit of the draw fields is not stated in the schema |
| EnergyPlus, `NREL/EnergyPlus` at `3659eb79…` | `datasets/Chillers.idf`, reference data from the CoolTools project | A BSD-style licence with a clause that forbids the name "EnergyPlus" in a company or product name, or in advertising or promotion, without the consent of the U.S. Dept. of Energy. The data set carries no terms of its own |
| MLPerf results, `mlcommons/inference_results_v6.1` | Measured power and performance of AI systems | Apache-2.0 for that repository. The rules on publishing results were not read |
| SPECpower results | Measured server power by load | A fair-use page that asks for the source and the retrieval date, and forbids presenting a derived value as a SPEC metric. Read through a summary only |
| ENERGY STAR certified UPS | Products, capacity and efficiency | Not read |

## Decisions

### 1. The registry is a directory of entries

`equipment/<module>/<id>.yaml` holds one entry: one make and model, the values it gives one module, and four records about those values.

| Record | Holds |
| --- | --- |
| `provenance` | the source, the record in it and its lines, the data type (`factual_specification`, `measurement` or `vendor_statement`), and `redistributes_source_document: false` |
| `simulation` | whether the model is independently developed or supplied by the maker, `manufacturer_validated`, and `calibration` |
| `rights` | `commercial_use` and `redistribution`, each `allowed`, `pending_review` or `denied`, the basis, and the review date |
| `rated_conditions` and `fit` | the conditions the source rated the values at, and in words how the module takes them |

Every value has a `source` that cites the source, the file, the line and the commit. A registry value is never `assumed`.

### 2. Three tiers, each earned

- `factual`: the values a public source states, taken as stated.
- `calibrated`: values fitted to measurements the entry names. It must say `calibration: calibrated`.
- `vendor_verified`: the maker checked the values, by a statement the entry names in `verification`. Only such an entry may say `manufacturer_validated: true`.

A paid check of a model is a separate thing from a benchmark result, and buys no place in one. An entry's tier is shown on every facility card that uses it, and a card is never ranked by it.

### 3. The gate

`tests/conformance/test_equipment_registry.py` refuses the registry when any of these holds:

- an entry does not validate;
- an entry claims a tier it has not earned;
- a value cites no pinned source;
- the commercial use or the redistribution of an entry is anything but `allowed`;
- a source's licence text is not in `equipment/licences/`;
- `THIRD_PARTY_NOTICES.md` does not name a source's repository, commit and licence file;
- a value is one its module does not read (ADR 0033, decision 3).

An entry whose rights are pending review is kept out of the repository until they are decided.

### 4. Sources are pinned, and entries are made by tools

`equipment/sources.yaml` pins each source: its repository, commit and the SHA-256 of each file read, its licence, its attribution and the names that may not be used. An importer per source writes the entries from the pinned file, and `--check` makes them again and fails on any difference. The first importer, `tools/equipment_modelica.py`, reads chiller records. The source files themselves are not copied into the repository.

### 5. What is taken, and what is not

- **Facts, not documents.** Values are taken from a file as numbers, each citing its line. No datasheet, drawing or text of a source is copied. For the Modelica records, the record's name, the rated capacity, the COP, the rated temperatures and the minimum part-load ratio are taken. The performance curves are not taken, because `cooling.chw_plant` has curves of its own.
- **The fit is stated.** The Modelica records are water-cooled chillers rated at their own conditions. `cooling.chw_plant` is an air-cooled plant of identical chillers. Each entry says so in `fit`, and takes only capacity and COP.
- **No endorsement and no names in promotion.** Makers are named because the source names them, to say which equipment a record describes. Nothing says that a maker has checked or endorses an entry, unless the entry is `vendor_verified`. The names that a source's licence protects, the institutions behind Modelica Buildings and the name "EnergyPlus", appear only in provenance and notices, never in a name, a heading or promotion of this project.

### 6. First entries

Eight chiller records of Modelica Buildings: Trane RTHB, Carrier 23XL (two), Carrier 19XR, York YS (two) and York YT (two). They are all `factual`.

## Requirements

| ID | Requirement |
| --- | --- |
| `ADC-EQP-001` | Every entry validates, lies at `<module>/<id>.yaml`, names a pinned source, and each value cites that source's file and commit. |
| `ADC-EQP-002` | Every entry in the repository may be used commercially and redistributed. A tier is never claimed beyond what the entry shows. |
| `ADC-EQP-003` | A bundle names an entry as `registry:<id>`; every value of every entry is read by its module, and an unknown entry is refused. |
| `ADC-EQP-004` | `THIRD_PARTY_NOTICES.md` names every source's repository, commit and licence file. |

## Next

- **NetBox device types,** for IT equipment, once a module reads per-device power. Today `electrical.it_load` takes one design load per POD. The unit of the draw fields has to be settled first.
- **UPS data from ENERGY STAR,** once its terms are read.
- **Measured server power from MLPerf and SPECpower,** under their publication rules, as calibration data and not as registry values.
- **Calibrated entries,** from the calibration data contributed under `docs/calibration/`.
- **Vendor-verified entries,** from makers who check their own.

## Consequences

- An operator can build a facility from named equipment and see, on the card, where each value came from and how far it has been checked.
- Every entry can be redistributed, including in commercial use, under the terms its source sets. Those terms travel with the entry.
- The registry grows by one rule. Something whose rights cannot be shown does not enter, however useful it would be.
