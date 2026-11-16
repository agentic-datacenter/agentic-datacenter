# Candidate measurement datasets for Agentic Datacenter calibration

**Recorded:** 2026-11-14  
**Status:** Source register and calibration plan only. No dataset was imported, calibrated or validated as part of this note.

## Purpose

Replace unnecessarily static assumptions in Agentic Datacenter's energy and thermal What-If calculations with traceable, time-varying measurements. Calibrate individual physical submodels first; do **not** claim that a mixed collection of datasets validates one complete data center.

## Source register

| Priority | Source | Measurement scope | Intended Agentic Datacenter use | Rights / caveats |
| --- | --- | --- | --- | --- |
| P1 | [BodenType Data Center One (BTDC), RISE / Fraunhofer](https://fordatis.fraunhofer.de/handle/fordatis/171?locale=en), [DOI 10.24406/fordatis/87](https://doi.org/10.24406/fordatis/87) | Published hourly records covering 364 days / 8,736 hours, including energy, temperatures, humidity, server utilisation, fan speed and weather | Annual and daily demand profiles, outdoor-temperature sensitivity, aggregate facility/IT/cooling model checks where measurement boundaries align | Confirm the exact Creative Commons licence and use conditions before redistribution |
| P1 | [Aalborg University high-resolution server-room measurements](https://doi.org/10.5281/zenodo.21262042), [earlier Zenodo record](https://zenodo.org/records/19398358) | Experimental server load, temperature, airflow and power series, with high-frequency measurements and defined load points | Transient temperature response, heat transfer, airflow and server-load sensitivity | Verify record version and attribution/licence at ingestion; experimental room, not a representative whole facility |
| P1 | [RISE HEATWISE server-cooling dataset](https://zenodo.org/records/23237930) | Measurements from nine servers, including five-minute power, temperature, airflow, pressure and liquid/air cooling quantities | Component-level heat generation and cooling-response calibration | Listed as CC BY 4.0; preserve provenance and attribution |
| P2 | [AAU / Poznań PSNC cooling experiments](https://zenodo.org/records/22797095) | Controlled IT-load and cooling conditions, temperatures, energy and thermal performance indicators; available fields differ by site | Validate direction and magnitude of hypothetical thermal What-If interventions | Verify the exact record licence. Do not use the Poznań subset to claim electricity savings where no power measurement exists |
| P2 | [CINECA Marconi A2 / HazardNet](https://zenodo.org/records/10050368) | HPC-node power and inlet/outlet-temperature telemetry | IT load variability, hotspots and anomaly scenarios | Node measurements do not by themselves validate chiller/UPS/PUE; check original licence |
| P2 | [Google Cluster Data / PowerData2019](https://github.com/google/cluster-data/blob/master/PowerData2019.md) | Published data-center power-domain traces | Varying electrical load profiles and temporal stress tests | Confirm field definitions, permitted reuse and representativeness; no whole-site thermodynamic validation |

## Ingestion and calibration sequence

1. **Provenance first:** For each acquired dataset, store source URL/DOI, version, author, collection period, timezone, units, sensor and meter boundaries, missing-data policy, redistribution status and a SHA-256 manifest. Do not commit third-party raw data without clearance.
2. **Start with the existing input path:** Use `agentic-datacenter-data` and `cooling.weather` in `source: measured` mode for time-varying outdoor dry-bulb temperature and humidity. This path already exists. Additional measured IT-power and cooling-power feeds are **proposed future work**, not a claimed existing feature.
3. **Calibrate components:** Fit thermal inertia, heat transfer, fan/pump response and cooling performance only against datasets that measure the required inputs and outputs. Keep physical parameters bounded and document uncertainty.
4. **Independent validation:** Split fitting and holdout periods or load conditions. Report temperature and power MAE/RMSE, aggregate kWh error, and PUE error *only* where consistently measured facility/IT boundaries permit it. Avoid leakage across fit/test windows.
5. **What-If A/B/C:** Replay the same weather and IT-load traces in A baseline, B physically hypothetical intervention, and C contract-governed agent execution. Report differences in kWh, %, thermal margins, approvals, blocked actions and uncertainty intervals. Do not present B's theoretically possible savings as C's realised savings.
6. **Sensitivity:** Present conservative, central and optimistic estimates; distinguish energy (kWh) from monetary value (NOK), which requires declared tariff and demand-charge assumptions.

## Validation boundary

These sources can improve **individual submodels** and scenario realism, but none is sufficient to validate the fidelity of the entire Agentic Datacenter plant, UPS dynamics, protection, chiller controls or real-world autonomous execution. Measurements from distinct sites must not be spliced into a fictional "measured site-wide PUE".

A valuable later step is an NDA-governed, aggregated export from a willing data-center operator: timestamp, outdoor air temperature/humidity, IT power, site or cooling power, supply/return temperature, and operating mode where safely shareable. Exclude tenant identities, network maps, credentials, network logs and physical-security details.

## Proposed acceptance criteria for a calibration claim

- Reproducible run pinned to Agentic Datacenter commit, dataset version and SHA-256.
- Traceable measurement units, time alignment and meter boundaries.
- Separate fit and holdout evidence; metrics and error distributions disclosed.
- Same exogenous inputs and initial conditions for baseline and proposed strategy.
- Explicit confidence/uncertainty interval and applicability limits.
- Third-party data redistribution and commercial-use rights recorded before inclusion in a product.

**Repository note:** The source list was prepared on 2026-11-14 for future calibration work. Links are candidates, not evidence that datasets have already been downloaded, licensed for redistribution, fitted, or benchmarked.
