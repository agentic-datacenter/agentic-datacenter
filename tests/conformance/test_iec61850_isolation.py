"""ADC-IEC-005: the protocol library is used in ``agentic-datacenter-iec61850`` only.

The import-linter contract in the workspace root is the first check. These
tests are the second: they read the sources and the packaging, and they import
every other package with the library and the optional package blocked.
"""

import ast
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PACKAGE = "agentic-datacenter-iec61850"
LIBRARY = "pyiec61850"
OTHERS = (
    "agentic_datacenter.core", "agentic_datacenter.plant", "agentic_datacenter.supervisory",
    "agentic_datacenter.net", "agentic_datacenter.governance", "agentic_datacenter.scenarios",
    "agentic_datacenter.whatif",
)  # fmt: skip


def imports(source: str) -> set[str]:
    found = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            found |= {alias.name.split(".")[0] for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module.split(".")[0])
    return found


@pytest.mark.req("ADC-IEC-005")
def test_only_one_module_of_one_package_imports_the_library() -> None:
    users = [
        str(path.relative_to(REPO))
        for path in sorted(REPO.glob("packages/*/src/**/*.py")) + sorted(REPO.glob("tools/*.py"))
        if LIBRARY in imports(path.read_text(encoding="utf-8"))
    ]
    assert users == [f"packages/{PACKAGE}/src/agentic_datacenter_iec61850/library.py"]


@pytest.mark.req("ADC-IEC-005")
def test_no_other_package_imports_the_optional_package() -> None:
    for path in sorted(REPO.glob("packages/*/src/**/*.py")):
        if path.relative_to(REPO).parts[1] != PACKAGE:
            assert "agentic_datacenter_iec61850" not in imports(path.read_text(encoding="utf-8")), (
                path
            )


@pytest.mark.req("ADC-IEC-005")
def test_no_other_package_depends_on_the_library_or_on_the_optional_package() -> None:
    for pyproject in sorted(REPO.glob("packages/*/pyproject.toml")):
        if pyproject.parent.name != PACKAGE:
            text = pyproject.read_text(encoding="utf-8")
            assert LIBRARY not in text and PACKAGE not in text, pyproject
    root = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    assert PACKAGE not in root["project"]["dependencies"]
    assert root["dependency-groups"]["iec61850"] == [PACKAGE]
    assert PACKAGE not in str(root["dependency-groups"]["dev"])
    own = tomllib.loads((REPO / f"packages/{PACKAGE}/pyproject.toml").read_text("utf-8"))
    assert own["project"]["license"] == "GPL-3.0-or-later"
    pins = [d for d in own["project"]["dependencies"] if d.startswith(LIBRARY)]
    assert len(pins) == 1 and "<" in pins[0], "one dependency on the library, with an upper bound"
    licence = (REPO / f"packages/{PACKAGE}/LICENSE").read_text(encoding="utf-8")
    assert "GNU GENERAL PUBLIC LICENSE" in licence and "Version 3" in licence


@pytest.mark.req("ADC-IEC-005")
def test_the_import_contract_covers_every_other_package() -> None:
    root = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    contracts = root["tool"]["importlinter"]["contracts"]
    contract = next(c for c in contracts if "ADC-IEC-005" in c["name"])
    assert contract["type"] == "forbidden" and contract["forbidden_modules"] == [LIBRARY]
    assert set(contract["source_modules"]) == {*OTHERS, "agentic_datacenter_remora"}
    harness = next(c for c in contracts if c["source_modules"] == ["agentic_datacenter.scenarios"])
    assert "agentic_datacenter_iec61850" in harness["forbidden_modules"]


@pytest.mark.req("ADC-IEC-005")
def test_every_other_package_imports_with_the_library_and_the_optional_package_blocked() -> None:
    script = f"""
import importlib, pkgutil, sys

class Blocked:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] in ("{LIBRARY}", "agentic_datacenter_iec61850"):
            raise ImportError(name + " is blocked for this test")

sys.meta_path.insert(0, Blocked())
count = 0
for root in {OTHERS!r}:
    package = importlib.import_module(root)
    for found in pkgutil.walk_packages(package.__path__, root + "."):
        importlib.import_module(found.name)
        count += 1
assert not any(m.split(".")[0] in ("{LIBRARY}", "agentic_datacenter_iec61850") for m in sys.modules)
print(count)
"""
    done = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert int(done.stdout) > 100


@pytest.mark.req("ADC-IEC-005")
def test_one_job_runs_the_whole_suite_without_the_package_and_one_runs_the_protocol_tests() -> None:
    jobs = yaml.safe_load((REPO / ".github/workflows/integration.yml").read_text("utf-8"))["jobs"]
    without = "\n".join(step.get("run", "") for step in jobs["without-iec61850"]["steps"])
    assert "uv sync --frozen\n" in without + "\n" and "--group" not in without
    assert "find_spec('agentic_datacenter_iec61850') is not None" in without, (
        "it checks the package is absent"
    )
    assert "uv run pytest" in without.splitlines()
    protocol = "\n".join(step.get("run", "") for step in jobs["protocol"]["steps"])
    assert "uv sync --frozen --group iec61850" in protocol
    assert "library.version()" in protocol, "it fails, not skips, if the library does not load"
    for path in ("tests/protocol", "tests/conformance/test_iec61850_denied_services.py",
                 f"packages/{PACKAGE}/tests"):  # fmt: skip
        assert path in protocol
    unit = yaml.safe_load((REPO / ".github/workflows/pr.yml").read_text("utf-8"))["jobs"]["unit"]
    assert PACKAGE not in unit["strategy"]["matrix"]["package"]
