# Connection requirements

One file per set of requirements a system operator has set, proposed or recommended for data centers as consumers of power. `agentic-datacenter grid check <id>` plays a file against a facility; see [the guide](../docs/guides/grid-requirements.md) and [ADR 0044](../docs/design/adr/0044-connection-requirements.md).

Optional, and no part of the benchmark.

| File | Where | Status |
| --- | --- | --- |
| `no-nvf-2026-draft.yaml` | Norway, Statnett | proposed |
| `eu-entsoe-2025-position.yaml` | European Union, ENTSO-E | recommended |
| `ie-mpid-345.yaml` | Ireland, EirGrid | proposed |
| `fi-kjv2026-draft.yaml` | Finland, Fingrid | proposed |
| `us-miso-2026-proposal.yaml` | United States, MISO | proposed |

`contracts/` holds one contract on the workload of a POD, as a template that `agentic-datacenter grid contracts <id>` fills in from a requirements file, and `scenarios/` holds `GR-01` to `GR-03`, which `agentic-datacenter grid run <id>` plays under the controls you name ([ADR 0045](../docs/design/adr/0045-a-control-held-to-the-grid.md)). Neither is part of the benchmark's libraries.

A file holds only values that were read from the document it names. A value that was not read is left out, and the check then measures without a verdict. A file never says a facility complies with anything.
