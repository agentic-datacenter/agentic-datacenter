# The weekly scenario

One new scenario every Monday, sealed before it is shown. [How it works, and how to run it](../docs/bench/WEEKLY.md); the design decision is [ADR 0046](../docs/design/adr/0046-a-scenario-every-week.md).

- `register.yaml` lists every week: what is planned, the SHA-256 of each sealed file, and what has been released.
- `scenarios/` holds the released files. Each hashes to what the register sealed for it.

```sh
uv run python tools/weekly.py check
```

These scenarios are no part of a frozen benchmark version until a season takes them in.
