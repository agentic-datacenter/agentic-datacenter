# Run a scenario on measured weather

`cooling.weather` can take its outdoor conditions from a measured historical series instead of the synthetic daily cycle. This guide shows how to put any fixed-step weather series into Agentic Datacenter's format, describe it with a manifest, and run a scenario on it. The rules behind it are in [ADR 0018](../design/adr/0018-measured-input-series.md).

## Before you start

- **Keep the data outside the repository.** Put the dataset in a directory of its own outside the Agentic Datacenter checkout, for example `~/agentic-datacenter-datasets/<site>/`. No series, extract or converted file is committed, and `.gitignore` refuses the usual names as a backstop.
- **Write down the licence as the source states it.** Copy the publisher's words into the manifest; do not paraphrase or resolve them. Leave `redistribution` at `not_cleared` unless the owner holds written permission to redistribute.
- **Install the optional package.** `uv sync` in the workspace installs `agentic-datacenter-data`; elsewhere install `agentic-datacenter-plant[measured]` and `agentic-datacenter-scenarios[measured]`.

## 1. Convert the series to Agentic Datacenter's format

Agentic Datacenter reads one UTF-8 CSV per dataset:

```text
time_utc,dry_bulb,rel_humidity
2020-07-01T00:00:00Z,18.4,71
2020-07-01T01:00:00Z,17.9,
2020-07-01T02:00:00Z,17.5,76
```

- `time_utc`: ISO 8601 in UTC with the `Z` designator, to the second. Timestamps without it are refused. If the source gives local time, convert it, and say in the manifest how (in particular whether the source observes daylight saving time).
- Rows strictly increasing, on one fixed step (usually 3600 s). A missing row or an empty cell means "not measured"; never write a placeholder such as `-9999` or `NaN`.
- Value columns Agentic Datacenter reads: `dry_bulb` (temperature), `dew_point` (temperature), `rel_humidity` (%). Only the columns you have; `dry_bulb` is required by `cooling.weather`.
- Write a small conversion script for your source and keep it with the data, outside the repository. Record what it did (source columns used, time conversion, any derived column) in the manifest's `derivation`.

## 2. Write the manifest

```sh
uv run agentic-datacenter data manifest ~/agentic-datacenter-datasets/site-a/series.csv \
  --dataset-id site_a_2020 \
  --title "Hourly weather, site A, 2020" \
  --source "<publisher, URL of the files>" \
  --version "<release, tag or commit of the source>" \
  --doi "<DOI, if the source has one>" \
  --licence "<the licence exactly as the source states it>" \
  --redistribution not_cleared \
  --quality raw \
  --unit dry_bulb=degC --unit rel_humidity=% \
  --gap-tolerance-s 3600 \
  --derivation "<what the conversion script did>" \
  --extra ~/agentic-datacenter-datasets/site-a/convert.py
```

This writes `dataset_manifest.json` beside the series, with the period and the SHA-256 of every file taken from the files themselves. Temperatures may be declared in `degC`, `K` or `degF`; they are converted to °C.

`--gap-tolerance-s` is the longest stretch of missing samples Agentic Datacenter may bridge by linear interpolation (3600 = one missing hour on an hourly series; 0 = bridge nothing). Reading inside a longer stretch stops the run. Choose it before looking at results, and state it in any report.

## 3. Choose the window and check it

Pick the historical instant that simulated t=0 should stand for: the anchor. In a scenario run, t=0 is the start of the warm-up (600 s unless the scenario says otherwise), so the scenario itself starts that much later in the series. A run reads the series from the anchor for its warm-up and its whole length and stops if it runs past the end or into a gap beyond the tolerance. Check the window first:

```sh
uv run agentic-datacenter data check ~/agentic-datacenter-datasets/site-a/dataset_manifest.json \
  --anchor-utc 2020-07-28T05:00:00Z --seconds 173400
```

`--seconds` is the warm-up plus the scenario length (here 600 + 172800). It prints the dataset's provenance, the number and longest of the gaps it would bridge, and whether the window is covered.

## 4. Point a profile at it

Copy `profiles/generic_dc.yaml` to a path outside the repository and change the weather module:

```yaml
  - id: cooling.weather
    instances: [SITE]
    params:
      source: {value: measured, source: "ADR 0018"}
      manifest: {value: /home/me/agentic-datacenter-datasets/site-a/dataset_manifest.json, source: "user dataset, outside the repository"}
      anchor_utc: {value: "2020-07-28T05:00:00Z", source: "warmest three days of the series"}
      rel_humidity_pct: {value: 50.0, unit: "%", assumed: true}
```

`rel_humidity_pct` is used only when the series has no `rel_humidity` column. A relative `manifest` path is resolved from the directory the command runs in; an absolute path avoids surprises.

## 5. Run a scenario

```sh
uv run agentic-datacenter scenario run OP-01 --profile /home/me/site-a.yaml --seconds 3600 \
  --out /home/me/agentic-datacenter-runs/op01-site-a
```

Scenarios that inject weather (`OP-03`, `OP-10`, `OP-11`, `AD-01`, `AD-05`) override the series while the injection holds, as they override the synthetic cycle. To run one of them on the measured series alone, run a copy of the scenario without its weather line from a script, with `agentic_datacenter.scenarios.harness.run_scenario`.

## 6. Read the evidence

The bundle's `manifest.json` has a `measured_inputs` entry for the weather: the points derived from the series, `derived_from_measured_series: true`, `measurement_of_simulated_plant: false`, the anchor, the window, every gap bridged inside it, and the dataset's identity, licence, redistribution status and hashes. Its statements say that these inputs describe where and when they were measured, not the simulated facility. A run on recorded weather is not a calibration: no module becomes `F3`.

Two runs with the same profile, scenario, seed and files give identical state hashes. Changing a byte of the series makes the run refuse to start until the manifest is rewritten, and a rewritten manifest changes the state hashes.

Keep the bundles and any comparison with your data, outside the repository.
