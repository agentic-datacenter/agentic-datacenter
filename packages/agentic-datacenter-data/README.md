# agentic-datacenter-data

Measured input series, optional. Reads an hourly (or other fixed-step) time series in Agentic-Datacenter's own CSV format together with its `dataset_manifest.json`, verifies the SHA-256 of every file, and maps the series onto simulated time from an explicit anchor. The first consumer is `cooling.weather` with `source: measured`.

- Import path: `agentic_datacenter.data`
- May depend on: nothing else in Agentic-Datacenter
- Decision: `docs/design/adr/0018-measured-input-series.md`
- How to use it: `docs/guides/measured-weather.md`

No dataset is part of this distribution or of the repository. Datasets are supplied by the user at run time, from outside the repository.
