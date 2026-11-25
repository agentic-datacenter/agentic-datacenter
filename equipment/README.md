# The equipment registry

Named equipment with the values it gives a module of the simulator. Each entry records where every value came from and the right to use it. A facility bundle uses an entry by naming it (ADR 0033, ADR 0034):

```yaml
modules:
  - id: cooling.chw_plant
    instances: [CHW]
    equipment: registry:modelica.trane_rthb_531kw_4_83cop_valve
```

## What is in it

| Module | Entries | Source | Tier |
| --- | --- | --- | --- |
| `cooling.chw_plant` | 8 chillers: Trane RTHB, Carrier 23XL and 19XR, York YS and YT | Modelica Buildings Library, at the commit in `sources.yaml` | factual |

Each chiller entry takes the record's rated capacity and COP. The records are of water-cooled chillers, and `cooling.chw_plant` models an air-cooled plant. Each entry says so in `fit`, and keeps the rated conditions beside the values.

## Tiers

| Tier | Means | Shown on |
| --- | --- | --- |
| `factual` | the values a public source states, taken as stated | every card that uses the entry |
| `calibrated` | values fitted to measurements the entry names | the same |
| `vendor_verified` | values the maker has checked, by a statement the entry names | the same |

A tier says how far an entry has been checked. It never changes a ranking.

## Add an entry

1. **Pin the source.** Add it to `sources.yaml` with its repository, commit, the SHA-256 of each file read, its licence, its attribution and any names it protects. Put its licence text in `licences/`.
2. **Make the entries with a tool.** The tool reads the pinned file and cites the line of every value, as `tools/equipment_modelica.py` does. Its `--check` mode must make the same entries again.
3. **Record the rights.** `rights.commercial_use` and `rights.redistribution` must both be `allowed`, with their basis. An entry whose rights are pending review stays out of the repository.
4. **Name it in the notices.** Add the source to `THIRD_PARTY_NOTICES.md`.

`tests/conformance/test_equipment_registry.py` checks all of this, and that the entry's module reads every value it gives.

## Submit your own equipment, as a maker

1. Copy `TEMPLATE.vendor.yaml` to `equipment/<module>/<id>.yaml` and `TEMPLATE.source.yaml` into `sources.yaml`, and fill them in from your own data.
2. Run `uv run agentic-datacenter equipment check equipment/<module>/<id>.yaml`. It runs the registry's gate on your entry, and tries it in the generic facility.
3. Open a pull request.

An entry from a maker is under CC-BY-4.0 (`licences/CC-BY-4.0.txt`), with the attribution its source names. It is not under the contribution terms of `CONTRIBUTING.md`, so you grant no right to relicense it. You get your equipment in every facility that names it, with the entry's tier on every card that uses it.

**Makers are welcome to submit their own entries.** A maker's entry can reach `vendor_verified` with a statement of who checked it and when. Naming a maker in an entry says which equipment a record describes. It does not say that the maker has checked or endorses the entry, unless the entry is `vendor_verified`.
