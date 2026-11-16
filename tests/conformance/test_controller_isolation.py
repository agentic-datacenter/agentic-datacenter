"""ADC-MOD-003: a module's controller sees its declared I/O points, never the model.

A controller lives in ``controller.py`` and may import the kernel API and its
own module's ``points``; it may not import the model, the interlocks or any
other part of the plant. No module has a controller before Stage 2, so the
scanner is also tested on samples to show it would catch a violation.
"""

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
PLANT = REPO / "packages/agentic-datacenter-plant/src/agentic_datacenter/plant"


def violations(source: str, package: str) -> list[str]:
    allowed_local = {f"{package}.points", f"{package}.io"}
    found = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            names = [alias.name for alias in node.names]
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                names = ["." * node.level + (node.module or "")]
            else:
                names = [node.module or ""]
        else:
            continue
        for name in names:
            if name.startswith("."):
                if name.lstrip(".") not in {"points", "io"}:
                    found.append(name)
            elif name.startswith("agentic_datacenter.plant"):
                if name not in allowed_local:
                    found.append(name)
            elif name.startswith("agentic_datacenter.") and not name.startswith(
                "agentic_datacenter.core"
            ):
                found.append(name)
    return found


PKG = "agentic_datacenter.plant.electrical.power_train"


@pytest.mark.parametrize(
    "source",
    [
        f"from {PKG}.model import BusModel",
        "from .model import BusModel",
        "from . import interlocks",
        "from agentic_datacenter.plant.electrical.genset.controller import x",
        "import agentic_datacenter.supervisory.points",
    ],
)
def test_scanner_reports_a_controller_that_reaches_past_its_points(source: str) -> None:
    assert violations(source, PKG)


@pytest.mark.parametrize(
    "source",
    [
        "from agentic_datacenter.core.module import Inputs",
        f"from {PKG}.points import IO",
        "from .points import IO",
        "import math\nfrom dataclasses import dataclass",
    ],
)
def test_scanner_accepts_a_controller_that_uses_only_its_points(source: str) -> None:
    assert violations(source, PKG) == []


@pytest.mark.req("ADC-MOD-003")
def test_no_controller_imports_its_model_or_another_module() -> None:
    problems = []
    for controller in sorted(PLANT.glob("**/controller.py")):
        package = ".".join(controller.parent.relative_to(PLANT.parents[1]).parts)
        problems += [
            f"{controller.relative_to(REPO)}: {name}"
            for name in violations(controller.read_text(encoding="utf-8"), package)
        ]
    assert problems == []
