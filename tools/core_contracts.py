"""Write the import contracts without the REMORA binding.

The full contracts in ``pyproject.toml`` need ``agentic_datacenter_remora`` to be importable,
and that needs read access to the REMORA repository. Pull-request jobs have no
such access, so they check this reduced set; the integration workflow checks
the full one.
"""

from __future__ import annotations

import sys
import tomllib
from pathlib import Path

OPTIONAL = "agentic_datacenter_remora"


def reduced(config: dict) -> dict:  # type: ignore[type-arg]
    """Return *config* with every mention of the REMORA binding removed."""
    out = dict(config)
    out["root_packages"] = [p for p in config["root_packages"] if p != OPTIONAL]
    contracts = []
    for contract in config["contracts"]:
        if contract.get("source_modules") == [OPTIONAL]:
            continue
        kept = dict(contract)
        for key in ("source_modules", "forbidden_modules", "modules"):
            if key in kept:
                kept[key] = [m for m in kept[key] if m != OPTIONAL]
        contracts.append(kept)
    out["contracts"] = contracts
    return out


def render(config: dict) -> str:  # type: ignore[type-arg]
    """Render an import-linter configuration as TOML."""

    def value(item: object) -> str:
        if isinstance(item, bool):
            return "true" if item else "false"
        if isinstance(item, list):
            return "[" + ", ".join(value(i) for i in item) + "]"
        return '"' + str(item) + '"'

    lines = ["[tool.importlinter]"]
    lines += [f"{k} = {value(v)}" for k, v in config.items() if k != "contracts"]
    for contract in config["contracts"]:
        lines += ["", "[[tool.importlinter.contracts]]"]
        lines += [f"{k} = {value(v)}" for k, v in contract.items()]
    return "\n".join(lines) + "\n"


def main(argv: list[str]) -> int:
    """Write the reduced configuration to the path given."""
    root = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    target = Path(argv[1])
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(render(reduced(root["tool"]["importlinter"])), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
