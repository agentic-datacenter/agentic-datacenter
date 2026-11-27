"""Every package the lock installs for a distribution is named in the notices.

A runtime package is one that ``uv.lock`` reaches from a distribution of this
repository through ``dependencies`` and the extras asked for, its own extras
included. The development groups (``dev``, ``test``, ``docs``, ``audit``) are
not followed: the notices name those tools apart, and they are not distributed.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[2]
NOTICES = REPO / "THIRD_PARTY_NOTICES.md"


def _name(text: str) -> str:
    """Return a package name as the packaging rules compare it."""
    return re.sub(r"[-_.]+", "-", text).lower()


def runtime_packages(lock: dict[str, Any]) -> dict[str, str]:
    """Return every third-party runtime package in *lock*, with its version."""
    packages = {package["name"]: package for package in lock["package"]}
    ours = {
        name
        for name, package in packages.items()
        if {"editable", "virtual"} & set(package["source"])
    }
    pending: list[dict[str, Any]] = []
    for name in sorted(ours):
        pending += packages[name].get("dependencies", [])
        for extra in packages[name].get("optional-dependencies", {}).values():
            pending += extra
    seen: set[tuple[str, tuple[str, ...]]] = set()
    while pending:
        wanted = pending.pop()
        key = (wanted["name"], tuple(sorted(wanted.get("extra", []))))
        if key in seen:
            continue
        seen.add(key)
        package = packages[wanted["name"]]
        pending += package.get("dependencies", [])
        for extra in wanted.get("extra", []):
            pending += package.get("optional-dependencies", {}).get(extra, [])
    return {name: packages[name]["version"] for name, _ in seen if name not in ours}


def named_in_notices() -> set[str]:
    """Return the names in backticks in the table of runtime dependencies."""
    text = NOTICES.read_text(encoding="utf-8")
    table = text.split("### Runtime dependencies", 1)[1].split("\n### ", 1)[0]
    return {_name(found) for found in re.findall(r"`([^`\s]+)`", table)}


def test_every_runtime_package_in_the_lock_is_named_in_the_notices() -> None:
    lock = tomllib.loads((REPO / "uv.lock").read_text(encoding="utf-8"))
    runtime = runtime_packages(lock)
    assert {"pydantic", "uvicorn", "cffi", "tzdata", "anthropic"} <= set(runtime)
    assert not {"pytest", "ruff", "mypy", "mkdocs", "pip-audit"} & set(runtime)
    named = named_in_notices()
    missing = sorted(name for name in runtime if _name(name) not in named)
    assert not missing, (
        "runtime packages in uv.lock that THIRD_PARTY_NOTICES.md does not name, "
        f"each to be added with its version and declared licence: {', '.join(missing)}"
    )


def test_the_check_finds_a_package_the_notices_do_not_name() -> None:
    lock = {
        "package": [
            {"name": "ours", "source": {"editable": "packages/ours"},
             "dependencies": [{"name": "served", "extra": ["fast"]}],
             "dev-dependencies": {"test": [{"name": "tool"}]}},
            {"name": "served", "version": "1.0", "source": {"registry": "r"},
             "optional-dependencies": {"fast": [{"name": "speedup"}], "slow": [{"name": "other"}]}},
            {"name": "speedup", "version": "2.0", "source": {"registry": "r"}},
            {"name": "other", "version": "3.0", "source": {"registry": "r"}},
            {"name": "tool", "version": "4.0", "source": {"registry": "r"}},
        ]
    }  # fmt: skip
    assert runtime_packages(lock) == {"served": "1.0", "speedup": "2.0"}
    assert "speedup" not in named_in_notices()
