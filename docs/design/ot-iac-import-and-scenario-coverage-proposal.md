# Design exploration: customer OT imports, POD equipment and scenario coverage

**Status:** Proposal for discussion; not an accepted ADR and not an implemented feature  
**Date:** 2026-11-19  
**Scope:** Agentic-Datacenter, What-if, benchmark, and future cross-industry OT test environments

Related: [What-if ADR 0019](adr/0019-what-if.md), [benchmark tiers](../bench/TIERS.md), [module registry](../reference/modules.md), [generic facility profile](https://github.com/darklordVirtual/agentic-datacenter/blob/main/profiles/generic_dc.yaml), [POD cooling model](modules/cooling.pod.md).

## Objective

Let an operator supply an authorized, offline export of their infrastructure and OT engineering configuration. Translate supported portions into a transparent, customer-specific simulation profile, augment it with physical equipment specifications and measurements, then run what-if and agent/governance tests with explicit coverage and uncertainty reports.

This should eventually work for data centers, building automation/HVAC, energy and industrial OT. The data-center model is the first domain, **not a guarantee** that every imported facility can be simulated.

## Principle: description is not behavior

Infrastructure as Code (IaC) can describe deployed resources and intended connections. It typically does **not** describe physical transients, sensor uncertainty, actuator dynamics, protective interlocks or device-specific failure behavior. Import must distinguish:
- **Discovered/declared topology** (what the export actually says)
- **Mapped simulation capability** (what our modules support)
- **Assumptions/defaults** (what we have inserted)
- **Calibrated characteristics** (what vendor data or measurements support)
- **Unsupported/unmapped parts** (explicit coverage gaps)

No inferred equipment limits should be presented as validated nameplate ratings.

## Input formats to evaluate

| Format or source | Potential content | Caveat |
| --- | --- | --- |
| Terraform / OpenTofu HCL, sanitized plan JSON | Compute, network, infrastructure resources and dependencies | Not plant physics; plans/state may contain secrets |
| Kubernetes YAML / rendered manifests | Workloads, services, workloads-to-network mapping | Never apply manifests during import |
| OPC UA NodeSet XML | OT data types, devices, point references, engineering units | Semantics and physical relationships can be incomplete |
| IEC 61850 SCL | Electrical IEDs, logical nodes and communication configuration | Configuration is not a protection-behavior proof |
| AutomationML / IEC 62714 | Engineering objects and plant hierarchy | Export completeness is tool-dependent |
| IFC / Brick | Building/equipment spatial and semantic relationships | Often lacks control loop dynamics |
| FMI / FMU | Supplied executable dynamic models or co-simulation components | Untrusted executable code: isolated workers, strict allowlists and resource caps |
| Vendor datasheets, BMS/SCADA point lists, trends and event histories | Nameplate limits, control sequences, measured responses and calibration | Quality/provenance and permission checks required |

Prioritize parsers by available customer samples and meaningful simulation coverage, not by format popularity.

## Proposed import architecture (read-only)

1. **Offline ingestion:** accept explicitly provided files only; schema and size validation, no live connection and no writes to equipment.
2. **Static parsing and normalization:** map sources to a canonical graph of site > zones > PODs > assets > points > ports > connections. Do not execute arbitrary Terraform, Kubernetes, templates, vendor scripts or imported FMUs during parsing.
3. **Semantic mapping:** identify simulation module types (`cooling.pod`, `electrical.it_load`, `electrical.ups`, etc.) and attach parameter values with units, bounds, source references and confidence/provenance.
4. **Gap detection:** flag assets and control sequences without an equivalent physical model; do not silently substitute defaults or infer protection capabilities.
5. **Simulation-profile generation:** emit a candidate profile with explicit assumptions, versioned mapping decisions and a reviewable diff against source data.
6. **Validation and scenario generation:** validate graph connectivity and physical consistency, vary only meaningful parameters, and create what-if cases / benchmark runs against the reviewed profile.
7. **Evidence/reporting:** provide input hashes, simulator/model version, source-to-asset mappings, parameter provenance, supported behavior, uncovered behavior, and observed test coverage.

A customer-imported environment must remain simulation-only. Agent actions use simulated points and an isolated governance adapter, never customer OT endpoints.

## Equipment register per POD: recommended next work

**Yes: a per-POD bill of equipment and technical specification register is essential.** The current generic profile has 16 PODs, each modeled at 150 kW IT design load and 12 kg/s design airflow, with rotating dual A/B feeds from three trains. The POD cooling model assumes four AHUs (three carry design flow, N+1), six zone sensors, 6 kW fan power, 4,500 kJ/K thermal mass, and a critical supply-air threshold above 32 C for more than 60 seconds. **These are generic, assumed simulator settings, not sourced equipment specifications from a real site.**

Recommended data structure per asset:
- `site_id`, `pod_id`, `asset_id`, `asset_type`, `manufacturer`, `model`, `revision`, `firmware` (when relevant)
- `nameplate` and rated capacity, electrical feeds, connections and redundancy group
- `operating_envelope`: manufacturer-permitted min/max values, normal setpoints, alarm/trip thresholds, units and conditions
- `dynamics`: thermal mass, start/stop and restart delays, ramp and valve stroke times, efficiency/flow curves, hysteresis
- `control_interface`: measurable points, writable points, permissible actions, permissions, interlocks and fail-safe behavior
- `fault_modes`: realistic failure and degraded states, detection delays and dependencies
- `evidence`: datasheet/revision, on-site measurements, calibration dates, model fidelity and explicit assumptions

Initially include IT racks/load, AHUs/fans, coils/valves, sensors, fire/EPO connections, A/B supply paths, and upstream dependencies (UPS, cooling distribution, pumps and chillers).

**Distinct configuration matters:** avoid assuming 16 identical PODs. Support different occupancy, IT load, AHU models, redundancy, sensor placements, control firmware and maintenance state. Site/profile overrides should take precedence over the generic template.

## Test dimensions and coverage (proposed, not yet measured)

Use separate dimensions for:
- **Operating condition:** IT load, outdoor temperature, cooling setpoint, charge/SoC and equipment utilization.
- **Failure/degradation:** chiller or AHU unavailable, reduced flow, stuck valve, sensor drift/stale value, utility loss, failed restart, network partition, delayed commands and combined faults.
- **Governance/adversarial behavior:** unauthorized writes, approval bypass, replay, stale premises, permission changes and agent mistakes.
- **Time and uncertainty:** fault order, delay between faults, duration, seasonal cycles, measurement quality and model parameter uncertainty.

For each numeric dimension distinguish `normal`, `near_boundary`, `out_of_envelope`, and `fault` where meaningful. **Do not invent engineering min/max ranges** from the existing generic values; derive them from equipment/vendor data or explicitly mark them as synthetic test bounds. Include boundary values and pairwise/high-risk multi-fault combinations instead of an infeasible full Cartesian product.

Coverage report should state:
- supported vs imported assets, ports, points and control actions;
- equipment specifications verified vs assumed;
- scenario combinations covered by type and criticality;
- safety/governance violations, false blocks, human approvals and useful autonomy;
- model-fidelity limits and untested/unknown combinations.

A green benchmark on a fixed generic profile is **not** proof that all what-if scenarios or customer equipment states are mapped. Benchmark comparison and per-change What-if analysis are different operations.

## Suggested incremental delivery

**Phase 1: POD asset specification schema and coverage report.** Use the existing 16-POD generic profile as baseline; enumerate equipment, source/assumed values and gaps without changing frozen benchmark behavior.

**Phase 2: Read-only import proof of concept.** Start with one real, authorized export (e.g., OPC UA NodeSet/point list plus engineering data). Optionally add Terraform/OpenTofu and Kubernetes manifests for digital topology. Generate normalized graph and explicit unsupported mappings.

**Phase 3: Customer-specific What-if.** Import calibrated curves and dynamics, construct scenario sets around nameplate/operating limits and real fault dependencies, report baseline vs hypothetical vs governed outcomes.

**Phase 4: Broader OT adapters.** Assess AutomationML, IFC/Brick, IEC 61850 SCL and FMI/FMUs based on pilot data. Require independent validation before suggesting a model is representative of a physical installation.

## Decisions still open

1. Canonical interchange schema and versioning.
2. Which equipment types and input formats give the highest near-term coverage.
3. How to distinguish engineering limits, contract limits and benchmark stress-test bounds.
4. Model confidence scoring, calibration requirements and coverage denominator.
5. Import sandbox, secrets handling, tenancy, provenance and vendor licensing.
6. When to fork a versioned customer profile vs reuse generic modules.

**Immediate recommendation:** define the POD equipment register and provenance requirements first. That makes import quality and meaningful variability measurable before expanding the parser catalog.
