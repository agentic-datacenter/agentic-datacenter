"""A built distribution holds the text of its licence (ADR 0004, addendum on publication)."""

import importlib.util
import tarfile
import zipfile
from pathlib import Path
from types import ModuleType

import yaml

REPO = Path(__file__).resolve().parents[2]


def tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dist", REPO / "tools/check_dist_licences.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def build(dist: Path, name: str, text: str | None) -> None:
    """Write a wheel and a source distribution of one name, with or without a licence file."""
    with zipfile.ZipFile(dist / f"{name}-0.0.0-py3-none-any.whl", "w") as wheel:
        wheel.writestr(f"{name}-0.0.0.dist-info/METADATA", "Name: x\n")
        if text is not None:
            wheel.writestr(f"{name}-0.0.0.dist-info/licenses/LICENSE", text)
    source = dist / "src"
    source.mkdir(exist_ok=True)
    with tarfile.open(dist / f"{name}-0.0.0.tar.gz", "w:gz") as sdist:
        (source / "PKG-INFO").write_text("Name: x\n", encoding="utf-8")
        sdist.add(source / "PKG-INFO", f"{name}-0.0.0/PKG-INFO")
        if text is not None:
            (source / "LICENSE").write_text(text, encoding="utf-8")
            sdist.add(source / "LICENSE", f"{name}-0.0.0/LICENSE")


def test_distributions_with_their_licence_text_pass(tmp_path: Path) -> None:
    check = tool()
    for name, text in check.expected().items():
        build(tmp_path, name, text)
    assert len(check.expected()) == 10
    assert check.problems(tmp_path) == []


def test_a_missing_text_a_wrong_text_and_a_missing_distribution_are_named(tmp_path: Path) -> None:
    check = tool()
    texts = check.expected()
    for name, text in texts.items():
        if name == "agentic_datacenter_core":
            build(tmp_path, name, None)
        elif name == "agentic_datacenter_iec61850":
            build(tmp_path, name, texts["agentic_datacenter_core"])
        elif name != "agentic_datacenter_net":
            build(tmp_path, name, text)
    found = "\n".join(check.problems(tmp_path))
    assert "agentic_datacenter_core-0.0.0-py3-none-any.whl: the licence text is missing" in found
    assert "agentic_datacenter_core-0.0.0.tar.gz: the licence text is missing" in found
    assert (
        "agentic_datacenter_iec61850-0.0.0-py3-none-any.whl: the licence text is missing" in found
    )
    assert (
        "agentic_datacenter_net: no wheel" in found and "agentic_datacenter_net: no sdist" in found
    )
    assert len(check.problems(tmp_path)) == 6


def test_the_pull_request_and_the_release_build_every_distribution_and_check_it() -> None:
    for workflow, job in (("pr", "supply-chain"), ("release", "build")):
        data = yaml.safe_load((REPO / f".github/workflows/{workflow}.yml").read_text("utf-8"))
        runs = [step.get("run", "") for step in data["jobs"][job]["steps"]]
        built = [i for i, r in enumerate(runs) if "uv build --all-packages" in r]
        checked = [i for i, r in enumerate(runs) if "tools/check_dist_licences.py" in r]
        assert built and checked and built[0] <= checked[0], workflow
