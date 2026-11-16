# Agentic Datacenter

A simulation-only model of a data center's operational technology, partitioned into IEC 62443 zones and conduits, built to benchmark governance gates for AI operations agents.

Agentic Datacenter never connects to real equipment, and makes no claim of IEC 62443 certification.

- **Design.** The [design document](design/SDD-ADC-001.md) is the single build input. Decisions it leaves open are recorded as ADRs.
- **Reference.** Generated from the code on every build: the [module registry](reference/modules.md), the [wiring of the generic profile](reference/wiring.md), the [requirement-to-test matrix](reference/requirements.md), the [command line](reference/cli.md) and the [profile schema](reference/profile_schema.md).
- **Module specs.** One per plant module, under `design/modules/`, linked from the module registry.
