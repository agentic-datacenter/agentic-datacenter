# Connection requirements

One file per set of requirements a system operator has set, proposed or recommended for data centers as consumers of power. `agentic-datacenter grid check <id>` plays a file against a facility; see [the guide](../docs/guides/grid-requirements.md) and [ADR 0044](../docs/design/adr/0044-connection-requirements.md).

Optional, and no part of the benchmark.

| File | Where | Status |
| --- | --- | --- |
| `no-nvf-2026-draft.yaml` | Norway, Statnett | proposed |
| `eu-entsoe-2025-position.yaml` | European Union, ENTSO-E | recommended |
| `ie-mpid-345.yaml` | Ireland, EirGrid | proposed |

A file holds only values that were read from the document it names. A value that was not read is left out, and the check then measures without a verdict. A file never says a facility complies with anything.
