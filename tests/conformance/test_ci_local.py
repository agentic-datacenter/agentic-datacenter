"""The local runner executes the workflows as written (ADR 0011)."""

import importlib.util
import sys
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
PR = REPO / ".github/workflows/pr.yml"


def tool() -> Any:
    spec = importlib.util.spec_from_file_location("ci_local", REPO / "tools/ci_local.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_plan_has_every_job_of_the_workflow_and_every_command_it_runs() -> None:
    ci = tool()
    workflow = yaml.safe_load(PR.read_text())
    plan = ci.plan(PR, docker=True)
    assert {job.context for job in plan} == set(workflow["jobs"])
    for name, spec in workflow["jobs"].items():
        written = [step["run"] for step in spec["steps"] if "run" in step]
        legs = [job for job in plan if job.context == name]
        matrix = spec.get("strategy", {}).get("matrix", {})
        assert len(legs) == max(1, len(next(iter(matrix.values()), [None])))
        for leg in legs:
            assert len(leg.commands) == len(written)
            assert leg.image == spec["container"] and "@sha256:" in leg.image


def test_matrix_is_expanded_and_no_expression_is_left() -> None:
    plan = tool().plan(PR, docker=False)
    unit = [job for job in plan if job.context == "unit"]
    assert [job.name for job in unit][:2] == [
        "unit (agentic-datacenter-core)",
        "unit (agentic-datacenter-data)",
    ]
    assert any("--package agentic-datacenter-core " in c for c in unit[0].commands)
    assert not [c for job in plan for c in job.commands if "${{" in c]


def test_the_base_branch_of_a_pull_request_is_filled_in() -> None:
    """Only GitHub knows the base branch; the pin-bump workflow compares with it."""
    bump = REPO / ".github/workflows/pin-bump.yml"
    assert "${{ github.base_ref }}" in bump.read_text()
    commands = [c for job in tool().plan(bump, docker=False, base="release") for c in job.commands]
    assert any('"origin/release...HEAD"' in c for c in commands)
    assert any('"origin/release"' in c for c in commands)
    assert not [c for c in commands if "${{" in c]


def test_on_the_host_the_image_setup_step_is_left_out_and_nothing_else() -> None:
    ci = tool()
    host, image = ci.plan(PR, docker=False), ci.plan(PR, docker=True)
    for a, b in zip(host, image, strict=True):
        dropped = [c for c in b.commands if c not in a.commands]
        assert all("apt-get" in c for c in dropped) and len(dropped) <= 1
        assert not [c for c in a.commands if "apt-get" in c]


def test_each_job_gets_its_own_environment_so_the_working_one_is_untouched() -> None:
    ci = tool()
    job = ci.plan(PR, docker=False)[0]
    env = ci.host_environment(job, REPO)
    assert env["UV_PROJECT_ENVIRONMENT"].startswith(str(REPO / "build/ci/venv"))
    assert env["UV_PROJECT_ENVIRONMENT"] != str(REPO / ".venv")


def test_one_status_per_job_under_the_name_the_ruleset_requires() -> None:
    ci = tool()
    results = [
        ci.Result("unit (agentic-datacenter-core)", "unit", True, 10.0, "host"),
        ci.Result("unit (agentic-datacenter-net)", "unit", False, 5.0, "host"),
        ci.Result("static", "static", True, 30.0, "host"),
    ]
    statuses = {s["context"]: s for s in ci.statuses(results)}
    assert (
        statuses["unit"]["state"] == "failure"
        and "agentic-datacenter-net" in statuses["unit"]["description"]
    )
    assert statuses["static"]["state"] == "success"
    assert "locally" in statuses["static"]["description"]
    required = {
        c["context"]
        for rule in yaml.safe_load((REPO / ".github/rulesets/main.json").read_text())["rules"]
        if rule["type"] == "required_status_checks"
        for c in rule["parameters"]["required_status_checks"]
    }
    assert required <= {job.context for job in ci.plan(PR, docker=False)}


def test_a_result_is_published_only_for_a_commit_that_is_what_was_tested() -> None:
    ci = tool()
    with pytest.raises(SystemExit, match="uncommitted"):
        ci.publishable(dirty=True, pushed=True)
    with pytest.raises(SystemExit, match="not pushed"):
        ci.publishable(dirty=False, pushed=False)
    ci.publishable(dirty=False, pushed=True)
