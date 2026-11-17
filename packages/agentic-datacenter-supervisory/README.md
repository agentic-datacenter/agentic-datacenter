# agentic-datacenter-supervisory

L3 Supervisory. Point database, alarm engine, historian, operator roles, Supervisory Command Service and read API.

- Import path: `agentic_datacenter.supervisory`
- May depend on: `agentic-datacenter-core`

| Module | What it is |
| --- | --- |
| `points` | Every point of every module, with quality; stale after three missed polls |
| `command_service` | The only writer to controllers; ordered checks, distinct reason codes, change log |
| `alarms` | Priorities, four states, deadbands, start-up and out-of-service suppression |
| `logs` | Append-only, hash-chained logs; an attempt to change one is refused and logged |
| `sessions` | Four permission levels; view-only after fifteen minutes idle |
| `historian` | Real-time values every second, energy every fifteen minutes |
| `overview` | Redundancy, energy and PUE derived from the points |
| `station`, `api` | The layer assembled, and its FastAPI application |

Decisions specific to this package are in `docs/design/adr/0009-supervisory-storage-and-api.md`.
