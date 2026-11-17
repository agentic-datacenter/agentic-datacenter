# agentic-datacenter-iec61850

Protocol, optional. One IEC 61850 MMS server per protection relay of the 36 kV switchboard, and the SCL files they are built from. The only distribution that uses the GPLv3 protocol library, and for that reason licensed GPL-3.0-or-later (`LICENSE` in this directory; ADR 0004).

- Import path: `agentic_datacenter_iec61850`
- May depend on: `agentic-datacenter-core`, `agentic-datacenter-supervisory`
- Library: `libiec61850` 1.6.1 from the `pyiec61850-ng` wheel, Linux only (ADR 0017)

| Module | What it is | Needs the library |
| --- | --- | --- |
| `model` | The six relays: logical nodes, data objects, and the point behind each served value | no |
| `scl` | SCD and ICD generation, and the reader the server is built from | no |
| `view` | The relays as views of the point database; refused requests as events | no |
| `server` | `Iec61850Server`: one relay on one port | yes |
| `client` | `MmsClient`: the client the protocol tests use | yes |
| `library` | The only module that imports the library | yes |

```sh
uv run --group iec61850 agentic-datacenter scl export --profile profiles/generic_dc.yaml --out build/scl
```

## Licence

This distribution is GPL-3.0-or-later. The packages it depends on, `agentic-datacenter-core` and `agentic-datacenter-supervisory`, and the plant it serves are under the Business Source License 1.1, and the server runs in one process with them. You may run that. You may not convey the library, this distribution and those packages together as one work, for example in a container image, because the two licences are not compatible (ADR 0004).
