"""ADC-KRN-003: no wall clock and no unseeded randomness outside core/clock.py.

The ruff banned-API rule catches the common spellings while editing. This test
is the backstop: it walks the syntax tree of every source file, so an aliased
import or a new package is covered without touching the lint configuration.
"""

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
ALLOWED = {Path("packages/agentic-datacenter-core/src/agentic_datacenter/core/clock.py")}

BANNED_MODULES = {"time", "secrets"}
BANNED_ATTRIBUTES = {
    "datetime": {"now", "utcnow", "today"},
    "date": {"today"},
    "os": {"urandom", "getrandom"},
    "uuid": {"uuid1", "uuid4"},
}
SEEDED_RANDOM_NAMES = {"Random"}


def violations(source: str) -> list[str]:
    """Return one message per wall-clock or unseeded-random use in *source*."""
    found: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in BANNED_MODULES:
                    found.append(f"line {node.lineno}: import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            module = (node.module or "").split(".")[0]
            if module in BANNED_MODULES:
                found.append(f"line {node.lineno}: from {node.module} import ...")
            if module == "random":
                for alias in node.names:
                    if alias.name not in SEEDED_RANDOM_NAMES:
                        found.append(f"line {node.lineno}: from random import {alias.name}")
        elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name | ast.Attribute):
            # `datetime.now` and `datetime.datetime.now` both have owner `datetime`.
            value = node.value
            owner = value.id if isinstance(value, ast.Name) else value.attr
            attr = node.attr
            if attr in BANNED_ATTRIBUTES.get(owner, set()):
                found.append(f"line {node.lineno}: {owner}.{attr}")
            if owner == "random" and attr not in SEEDED_RANDOM_NAMES:
                found.append(f"line {node.lineno}: random.{attr}")
        elif isinstance(node, ast.Call) and not node.args and not node.keywords:
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name == "Random":
                found.append(f"line {node.lineno}: Random() without a seed")
    return found


@pytest.mark.parametrize(
    "source",
    [
        "import time",
        "import time as t",
        "from time import monotonic",
        "import secrets",
        "import datetime\ndatetime.datetime.now()",
        "from datetime import datetime\ndatetime.utcnow()",
        "from datetime import date\ndate.today()",
        "import os\nos.urandom(8)",
        "import uuid\nuuid.uuid4()",
        "import random\nrandom.random()",
        "import random\nrandom.seed(1)",
        "import random\nrandom.SystemRandom()",
        "from random import randint",
        "from random import Random\nRandom()",
        "import random\nrandom.Random()",
    ],
)
def test_scanner_reports_each_forbidden_use(source: str) -> None:
    assert violations(source)


@pytest.mark.parametrize(
    "source",
    [
        "import random\nrandom.Random(42)",
        "from random import Random\nRandom(seed)",
        "import datetime\ndatetime.timedelta(seconds=1)",
        "import uuid\nuuid.uuid5(ns, name)",
        "clock.now_ms",
    ],
)
def test_scanner_accepts_seeded_and_clock_free_code(source: str) -> None:
    assert violations(source) == []


@pytest.mark.req("ADC-KRN-003")
def test_no_source_file_reads_the_wall_clock_or_unseeded_randomness() -> None:
    sources = sorted(REPO_ROOT.glob("packages/*/src/**/*.py"))
    assert sources, "no source files found; the scan would pass vacuously"
    problems = [
        f"{path.relative_to(REPO_ROOT)}: {message}"
        for path in sources
        if path.relative_to(REPO_ROOT) not in ALLOWED
        for message in violations(path.read_text(encoding="utf-8"))
    ]
    assert problems == []
