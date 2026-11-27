# Contribute calibration data

Every plant module in Agentic-Datacenter is at fidelity `F1`: it behaves plausibly, but nothing has been checked against real equipment. Equipment manufacturers, operators, integrators and researchers can change that. Data you share makes a module `F2` or `F3`, and every result that depends on it more trustworthy.

| Fidelity | Means | What it takes |
| --- | --- | --- |
| `F2` reference-checked | Agrees with published performance data within a stated tolerance | Data sheets, performance curves, type-test results |
| `F3` field-calibrated | Agrees with measurements from a real facility | Measured time series; the data stays private unless its owner releases it |

## What is useful

| Equipment | Useful data | Module |
| --- | --- | --- |
| Chillers | Capacity and power against load and condenser or ambient temperature; restart and staging times | `cooling.chw_plant` |
| Pumps, fans, air handlers | Curves of flow, pressure and power against speed; response to a step change | `cooling.pump_station`, `cooling.pod` |
| Thermal storage | Charge and discharge rates, losses | `cooling.tes` |
| UPS | Efficiency against load; battery runtime; transfer behaviour | `electrical.ups` |
| Generators, fuel | Start and load-acceptance times, consumption against load | `electrical.genset`, `fuel` |
| Switchgear, transfer, protection | Transfer times, relay settings and trip curves | `electrical.mv_switchgear`, `electrical.power_train` |
| IT load | Power over time per rack, row or hall; inlet and outlet temperatures | `electrical.it_load`, `cooling.pod` |
| Sensors | Accuracy, drift, failure modes | `sensors` |

Small pieces count. One performance curve is enough to check one module.

## Before you share: anonymize

Nothing that identifies a site, a customer or a person may reach the repository. Before sharing, remove or coarsen:

- the site's name, address, coordinates and operator: give a climate zone or a country at most;
- customer, tenant and staff names, and e-mail addresses;
- serial numbers, asset tags, hostnames, IP addresses and drawing numbers;
- absolute dates, if they matter to you: a constant shift of the time axis is fine, as long as the season and time of day are kept and the shift is stated;
- absolute magnitudes, if they are sensitive: scaling to a stated rated value (per unit) is fine.

Model and type names of your own equipment may stay if you want them to; say so.

## How to share

1. **Describe the data by e-mail**, to the contact address in [`COMMERCIAL_LICENSING.md`](https://github.com/agentic-datacenter/agentic-datacenter/blob/main/COMMERCIAL_LICENSING.md), with "Calibration data" in the subject. Say what it measures (equipment, quantities, units), its period and sampling, whether it is published data, measured in operation or measured in a laboratory, the terms it is shared on, and whether you want to be credited by name. Do not attach the data yet. Do not open a public issue: an issue shows everyone who holds data, even when it contains none.
2. **Send the data** when a maintainer replies, by a private transfer agreed by e-mail. Agentic-Datacenter's maintainers can sign a non-disclosure agreement first.
3. **Check what is published.** Before anything is merged, you see the calibration report and every file that will be public. Your name, or your organisation's, becomes public only if you asked to be credited.

Preferred format: CSV or Parquet, timestamps in UTC, SI units, and one short sheet saying the sampling interval, what each meter measures and its accuracy.

## What happens to it

- **Data that may be redistributed** (for example under CC BY 4.0) can be committed with its licence, source and SHA-256.
- **Data that may not** stays outside the repository. Only what is fitted from it is published: the module's parameters, the error against the data (fit and hold-out kept apart), and the data's hash, so a calibration can be checked by anyone the owner shares the data with.
- The module's fidelity is raised only through a calibration report, reviewed like any other change. A result made on it states the new level.
- You are credited by name in `THIRD_PARTY_NOTICES.md` and the calibration report, or not at all if you prefer.

## What it does not mean

A calibrated module is not an endorsement of your equipment, and a result made with it is still a simulation, not a statement about any site. Agentic-Datacenter never connects to real equipment, and never asks for access to a control system.

Public datasets that could be used for calibration are listed in [Suggested resources](suggested_resources.md).
