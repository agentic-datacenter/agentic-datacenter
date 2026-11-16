"""Compare the installed REMORA commit and uv.lock with REMORA_PIN (ADC-PIN-002, -003)."""

from __future__ import annotations

import json
import re
import sys
from importlib.metadata import distribution
from pathlib import Path


def pinned(text: str) -> str:
    """Return the commit recorded in REMORA_PIN."""
    match = re.search(r"^commit:\s*([0-9a-f]{40})\s*$", text, re.M)
    if match is None:
        raise SystemExit("REMORA_PIN has no 40-character commit line")
    return match.group(1)


def main() -> int:
    """Return 0 when lock and installed package both equal the pin."""
    pin = pinned(Path("REMORA_PIN").read_text(encoding="utf-8"))
    lock = Path("uv.lock").read_text(encoding="utf-8")
    locked = set(re.findall(r"REMORA-research\?rev=[0-9a-f]+#([0-9a-f]{40})", lock))
    direct = json.loads(distribution("remora-assurance").read_text("direct_url.json") or "{}")
    installed = direct.get("vcs_info", {}).get("commit_id")
    print(f"pin {pin}\nlock {sorted(locked)}\ninstalled {installed}")
    return 0 if locked == {pin} and installed == pin else 1


if __name__ == "__main__":
    sys.exit(main())
