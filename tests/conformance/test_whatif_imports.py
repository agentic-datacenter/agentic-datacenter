"""The what-if import contract names every module of the package but the policy adapter."""

import ast
import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
PACKAGE = REPO / "packages/agentic-datacenter-whatif/src/agentic_datacenter/whatif"
CONTRACT = "What-if reaches the REMORA binding from its policy adapter only (ADR 0019)"


def test_every_module_except_the_policy_adapter_is_kept_away_from_remora() -> None:
    config = tomllib.loads((REPO / "pyproject.toml").read_text(encoding="utf-8"))
    [contract] = [c for c in config["tool"]["importlinter"]["contracts"] if c["name"] == CONTRACT]
    modules = {
        f"agentic_datacenter.whatif.{p.stem}"
        for p in PACKAGE.glob("*.py")
        if p.stem not in ("__init__",)
    }
    assert set(contract["source_modules"]) == modules - {"agentic_datacenter.whatif.policy"}
    assert {"agentic_datacenter_remora", "remora", "servers"} <= set(contract["forbidden_modules"])


def test_the_policy_adapter_reaches_remora_only_through_the_binding() -> None:
    tree = ast.parse((PACKAGE / "policy.py").read_text(encoding="utf-8"))
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names += [a.name for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names.append(node.module or "")
    reaching = [name for name in names if "remora" in name or "servers" in name]
    assert reaching == ["agentic_datacenter_remora"], reaching
