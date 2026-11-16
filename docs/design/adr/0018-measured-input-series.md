# ADR 0018: Measured input series, starting with historical weather

- **Status:** Proposed. Accepted when the PR that adds it is merged by the owner.
- **Date:** 2026-11-13
- **SDD:** 5 (distributions and layers), 6.2 and 6.6 (weather), 6.7 (fidelity), 12 (evidence bundles); requirements `ADC-KRN-001`, `ADC-EVD-001`

## Context

`cooling.weather` produces outdoor dry-bulb temperature and humidity from a daily sine cycle, with scenario inputs for a constant and a heat wave. SDD 6.6 asks for an hourly weather file supplied by the user, and the module spec lists that reader as not written. A public dataset of measured building energy and weather data prompted the question of running scenarios on recorded weather instead of a synthetic cycle.

Measured data raises questions that synthetic data does not:

- **Mapping to simulated time.** The kernel counts integer milliseconds from zero (ADR 0006). A series is a sequence of historical instants. Something has to say which instant simulated t=0 stands for.
- **Resolution.** Weather is typically hourly; the thermal models step every second. Values between samples have to come from a stated rule.
- **Incompleteness.** Real series have missing hours and stop at an end date. Filling or extending them silently would put invented values into a run that claims to be driven by measurements.
- **Determinism.** A run must stay reproducible bit for bit (`ADC-KRN-001`). A file that changes on disk would change the run without changing the profile.
- **Provenance.** A value derived from a recorded series describes the place and time it was recorded, not the simulated facility. If an evidence bundle does not say so, a reader may take it for a measurement of the plant, or for a calibration (fidelity `F3`), which it is not.
- **Licence.** Datasets come with their own terms, sometimes stated inconsistently by the same publisher in different places. The repository is BUSL-1.1 (ADR 0004) and must not take on obligations, or redistribute data, on an unresolved reading of someone else's terms.

## Decision

### 1. A general measured-input layer, in its own optional distribution

A new distribution `agentic-datacenter-data`, import path `agentic_datacenter.data`, holds everything that reads measured data: the dataset manifest, the CSV reader, hash verification, unit conversion, interpolation and the `agentic-datacenter data` command. It is source-neutral: Agentic-Datacenter defines its own series format and manifest, and a dataset from any publisher is converted into that format outside the repository before use. No source-specific code, name or parameter is in the repository.

Why a separate distribution rather than code in `agentic-datacenter-core` or in the weather module:

- The kernel stays free of file reading and dataset concerns; it still imports nothing else in Agentic-Datacenter and needs no change.
- Weather is the first measured input, not the last (an IT load trace is the obvious second). A layer shared by modules avoids one reader per module, while modules stay independent of each other (`ADC-MOD-002`).
- It is optional. No distribution requires it. `agentic-datacenter-plant[measured]` and `agentic-datacenter-scenarios[measured]` pull it in; the workspace installs it by default (dependency group `data`) so its tests and type checks always run. `cooling.weather` and the evidence code import it only when a profile selects a measured source, and fail with a message naming the missing distribution otherwise.

Layering: `agentic_datacenter.data` imports nothing else in Agentic-Datacenter (a new import contract). `agentic_datacenter.plant` and `agentic_datacenter.scenarios` may import it; core, supervisory, net, governance and the IEC 61850 package may not. SDD section 5 lists it as a ninth distribution.

A source-specific distribution (for example one named after the first dataset) was considered and rejected: it would tie package names, and so the repository, to one publisher's data and terms, and a second dataset would need a second package.

### 2. Format and manifest, defined by Agentic-Datacenter

- **Series.** UTF-8 CSV. First column `time_utc`, ISO 8601 in UTC with the `Z` designator, to the second. Value columns from a fixed list (`dry_bulb`, `dew_point`, `rel_humidity`). Rows strictly increasing and on the declared step; a missing row or an empty cell means "no measured value". Timestamps without the UTC designator are refused, never guessed: converting from local time, with or without daylight saving, is the converter's job and is recorded in the manifest's `derivation`.
- **`dataset_manifest.json`** beside the series, schema version 1: `dataset_id`, `title`, `source`, `version`, `doi`, `licence` (as the source states it, verbatim; not an interpretation), `redistribution` (`not_cleared` or `cleared`), `quality_status`, `period` (first and last timestamp), `step_s`, `gap_tolerance_s`, `columns` with the unit of each, `series_file`, `files` (path and SHA-256 of every file, the series included), `derivation`, `notes`.
- **Units.** Temperatures in `degC`, `K` or `degF`, converted to °C; humidity in `%`. Any other unit is refused with `UnitNotUnderstood`.
- **Paths** in the manifest are relative and must stay inside the dataset directory.

`agentic-datacenter data manifest` writes the manifest from the files, so the period and hashes cannot be mistyped; `agentic-datacenter data check` verifies a dataset and, given an anchor and a length, that a run window is covered.

### 3. Mapping to simulated time

The profile gives the anchor explicitly: `anchor_utc` is the historical instant that simulated t=0 stands for. Simulated time `t` ms reads the series at `anchor + t`. There is no default anchor and no wrap-around: a run longer than the series fails when it reaches the end. In a scenario run, simulated t=0 is the start of the warm-up (600 s by default), so the scenario's own second 0 reads the series at `anchor + warm-up`; the bundle records both.

### 4. Interpolation, range and gaps

- **Rule.** Linear interpolation in time between the two nearest measured samples: at a sample the value is the sample, between samples `v0 + (v1 - v0) * (t - t0) / (t1 - t0)`. Time is integer milliseconds, so the same file gives the same values on every run. The weather module evaluates it at every one-second step.
- **No extrapolation.** Before the first or after the last measured value of a column, reading fails with `OutsideSeries`. This includes an anchor outside the series, which fails when the module is built.
- **Gaps: an explicit, declared fill; fail-closed beyond it.** The manifest declares `gap_tolerance_s`, the longest stretch of missing samples that may be bridged by the same linear rule (one missing hour on an hourly series is 3600 s). Reading inside a longer stretch fails with `GapTooLong`, naming the column, the stretch and the tolerance. A tolerance of 0 bridges nothing. The fill is never silent: the tolerance is in the manifest, whose hash is in the bundle, and every gap the run window crosses is listed in the bundle (section 6).
- **Errors** all derive from `MeasuredSeriesError` (a `ValueError`) and name the file or column: `DatasetFileMissing`, `HashMismatch`, `UnitNotUnderstood`, `ManifestInvalid`, `OutsideSeries`, `GapTooLong`.

### 5. Determinism

Same profile (which names the manifest and the anchor), same scenario, same seed and same files give the same state hash at every step. To make that hold even if a file changes:

- every file is hashed when the dataset is loaded and refused on a mismatch with its manifest, and the bytes that were hashed are the bytes that are parsed;
- the weather module's state includes the SHA-256 of the manifest (which carries the file hashes) and the anchor, so a run on other data cannot produce the same state hashes, and a snapshot cannot be restored onto another series;
- the evidence bundle records the SHA-256 of the manifest and of every file.

With the synthetic default nothing changes: the module's state, the profile and the bundle are the same as before this decision.

### 6. Provenance in the evidence bundle

When a profile uses a measured series, the bundle manifest gains `measured_inputs`, one entry per module instance, with:

- `instance` and `points` (the points whose values derive from the series);
- `derived_from_measured_series: true` and `measurement_of_simulated_plant: false`;
- `anchor_utc`, `window_utc` (the part of the series the run covered, warm-up included), `scenario_start_utc` and `bridged_gaps_in_window`;
- `dataset`: id, title, source, version, DOI, licence and redistribution status as the manifest states them, quality status, period, step, gap tolerance, units, the SHA-256 of the manifest and of every file, and the count and longest of the bridged gaps over the whole series.

The bundle's statements gain one: these inputs describe where and when they were measured, not the simulated facility, and nothing in the run is a measurement of the simulated plant. Paths are not recorded, so a bundle reproduced on another machine is byte-identical. The bundle schema version stays 1: the key is additive and absent for synthetic runs.

### 7. Fidelity

A measured input does not raise any module's fidelity. `cooling.weather` stays `F1`, and a run on recorded weather is not field-calibrated (`F3`): no part of the plant is compared with measurements of a real facility. Result cards keep stating that no `F3` claim is possible (SDD 6.7).

### 8. Scenario inputs

Scenario inputs keep their meaning in measured mode: `set` and `heat_wave` override the series, and `clear` returns to it. A scenario that injects weather therefore does not run on the measured series while the injection holds; to run a scenario on recorded weather alone, use one that does not inject weather, or a copy without that line.

### 9. Licence position

- No dataset, extract or series derived from one is committed to this repository or distributed with any Agentic-Datacenter distribution, evidence bundle published from it, or release. Datasets are fetched and converted by the user, kept outside the repository, and read at run time from a path the profile gives.
- Evidence bundles of runs on measured data contain hashes and metadata, not the series. Metric summaries derived from such runs are kept with the user's local data, not committed.
- Distribution of any derived dataset stays blocked until the owner holds a written licence clarification from the publisher. The manifest field `redistribution` defaults to `not_cleared` and is changed only on that basis.
- The publisher's licence is recorded verbatim in the manifest; Agentic-Datacenter does not interpret it.

### 10. Dependencies

None added. The reader uses the standard library (`csv`, `hashlib`, `json`, `bisect`, `datetime`) and `pydantic`, which section 5 already lists. pandas or NumPy would add a large dependency for a few thousand rows per dataset and is not justified.

## Consequences

- Scenarios can run on recorded outdoor conditions without any change to the kernel, to the port types or to the default profile.
- A run on measured data stops instead of inventing values when the data runs out or has a hole larger than declared. Choosing the anchor and the tolerance is the user's responsibility, and `agentic-datacenter data check` shows before a run whether a window is covered.
- Weather that changes every second keeps the thermal models awake; ADR 0006 measured such a day at about 65 s of stepping on the development machine. Long runs on measured weather are slower than on the constant default.
- The manifest format is a public interface of Agentic-Datacenter; changing it needs a new schema version.
- Not done here: a reader for other formats (such as EPW, SDD 6.6), measured IT load, and a field on the result card. Each is added through this layer when needed.
