# Module spec: `cooling.weather`

Outdoor conditions. Fidelity `F1`. Zone `Z1-BLDG`. Instances: one, for example `SITE`.

## Purpose

Dry-bulb temperature and relative humidity at the site, for the chillers: from a synthetic daily cycle (the default), or from a measured historical series (ADR 0018).

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `ambient` | provides | `weather` |

## Equations

**Synthetic** (`source: synthetic`, the default). `T = mean + swing * sin(2 * pi * (hour - 9) / 24)`: lowest at 03:00, highest at 15:00, with simulated time starting at midnight. A heat wave peaks at a given temperature and keeps the nights within half a daily swing of it. Humidity is constant.

**Measured** (`source: measured`). The series named by `manifest` is read through `agentic_datacenter.data` and its file hashes verified when the module is built. Simulated time `t` reads the series at `anchor_utc + t`. Between two measured samples `(t0, v0)` and `(t1, v1)` the value is `v0 + (v1 - v0) * (t - t0) / (t1 - t0)`, evaluated every second. Humidity comes from the series when it has a `rel_humidity` column, else from `rel_humidity_pct`. A time outside the series, or inside a stretch of missing samples longer than the manifest's `gap_tolerance_s`, stops the run with an error; nothing is extrapolated.

## State machine

Three modes: the profile source (synthetic cycle or measured series), a constant set by the scenario, and a heat wave. Scenario inputs override a measured series as they override the cycle; `clear` returns to the profile source.

## Points

`dry_bulb_c`, `rel_humidity_pct`; tier `T0` measurements.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `dry_bulb_c` | 20.0 | °C | `assumed: true` |
| `daily_swing_c` | 0.0 | K | `assumed: true` |
| `rel_humidity_pct` | 50.0 | % | `assumed: true` |
| `source` | `synthetic` | `synthetic` or `measured` | `assumed: true` |
| `manifest` | none; required when measured | path to `dataset_manifest.json`, outside the repository | the user's dataset |
| `anchor_utc` | none; required when measured | historical instant of simulated t=0, `YYYY-MM-DDThh:mm:ssZ` | the user's choice |

## Faults

Scenario inputs `set`, `heat_wave` with `peak_c`, and `clear`.

## Validation cases

- `packages/agentic-datacenter-plant/tests/cooling/test_cooling_modules.py`: the daily cycle, a heat wave and a constant.
- `packages/agentic-datacenter-plant/tests/cooling/test_weather_measured.py`: the anchor, values at and between samples, the end of the series, gaps, a changed file, scenario overrides, snapshot.
- `tests/scenario/test_measured_weather.py`: identical state hashes for the same file and seed, and provenance in the evidence bundle.
- The module contract suite.

## Known limits

- A measured series must first be converted to Agentic-Datacenter's CSV format with its manifest (ADR 0018). A reader for EPW files (SDD 6.6) is not written.
- Values derived from a measured series describe where and when they were measured, not the simulated site; they do not make this module, or any result, field-calibrated.
- Humidity has no effect on any model.
- No forecast is offered, so the pre-cooling contract has nothing to read yet.
