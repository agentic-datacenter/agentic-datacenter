# The weekly scenarios

Every week has scenarios of its own, drawn from a public randomness beacon, and nobody writes them. [How it works, and how to run them](../docs/bench/WEEKLY.md); the design decision is [ADR 0047](../docs/design/adr/0047-drawn-from-a-beacon.md).

```sh
uv run agentic-datacenter weekly show     # this week's scenario files
uv run agentic-datacenter weekly run      # run them under the two reference controls
```

Nothing is stored here for a week: the files are a function of the week and the beacon, the same for everyone.

`first/` holds the two scenarios that were written by hand and sealed on 2026-11-27, before the drawing replaced sealing the same day. They are shown as they were sealed:

| File | SHA-256, as registered on 2026-11-27 |
| --- | --- |
| `first/WK-01.yaml` | `77f5413dc5d5337caad7d16cd29a2e8bfb27747c6a7de95b474425ae2e2c25be` |
| `first/WK-02.yaml` | `b7cdf4da4e61454bc9658e9c83a00596d246d6d7063db9785326265731a16115` |

Their two patterns are among the kinds the generator draws from.
