"""Run a GitHub workflow of this repository on this machine (ADR 0011).

The repository cannot use hosted runners. This tool reads a workflow file and
runs the commands of its jobs here, either directly on the host or, with
``--docker``, inside the digest-pinned image the workflow names. It does not
keep its own list of checks: what it runs is what the workflow says.

With ``--publish`` it reports each job to GitHub as a commit status under the
job's name, which is the name the branch ruleset requires. A status is
published only for a commit that is pushed and has no uncommitted change, so
the status describes the commit and nothing else.

Examples::

    uv run python tools/ci_local.py --list
    uv run python tools/ci_local.py --job static --job conformance
    uv run python tools/ci_local.py --docker --publish
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time  # noqa: TID251 - a build tool timing a job, not simulator code
from dataclasses import asdict, dataclass
from itertools import product
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


@dataclass(frozen=True)
class Job:
    """One job, or one leg of a matrix job, with the commands it runs."""

    name: str
    context: str
    image: str
    commands: tuple[str, ...]


@dataclass(frozen=True)
class Result:
    """What happened to one job."""

    name: str
    context: str
    passed: bool
    seconds: float
    where: str


def plan(workflow: Path, docker: bool) -> list[Job]:
    """Return the jobs of *workflow* with matrices expanded.

    On the host the step that prepares the image (it installs git with the
    image's package manager) is left out; every other command is kept as
    written.
    """
    data = yaml.safe_load(workflow.read_text(encoding="utf-8"))
    jobs: list[Job] = []
    for context, spec in data["jobs"].items():
        matrix = spec.get("strategy", {}).get("matrix", {})
        keys = sorted(matrix)
        for values in product(*(matrix[k] for k in keys)) if keys else [()]:
            leg = dict(zip(keys, values, strict=True))
            commands = []
            for step in spec["steps"]:
                if "run" not in step:
                    continue
                command = str(step["run"])
                for key, value in leg.items():
                    command = re.sub(r"\$\{\{\s*matrix\." + key + r"\s*\}\}", str(value), command)
                if not docker and "apt-get" in command:
                    continue
                commands.append(command)
            name = f"{context} ({', '.join(str(v) for v in values)})" if leg else context
            jobs.append(Job(name, context, str(spec.get("container", "")), tuple(commands)))
    return jobs


def host_environment(job: Job, repo: Path) -> dict[str, str]:
    """Return the environment of a job on the host: its own virtual environment."""
    slug = re.sub(r"[^a-z0-9]+", "-", job.name.lower()).strip("-")
    inherited = {k: v for k, v in os.environ.items() if k != "VIRTUAL_ENV"}
    return {
        **inherited,
        "UV_PROJECT_ENVIRONMENT": str(repo / "build/ci/venv" / slug),
        "GITHUB_WORKSPACE": str(repo),
        "CI": "true",
    }


def _run(job: Job, repo: Path, docker: bool, log: Path) -> Result:
    start = time.monotonic()
    script = "set -eo pipefail\n" + "\n".join(job.commands) + "\n"
    with log.open("w", encoding="utf-8") as out:
        if docker:
            with tempfile.TemporaryDirectory(prefix="agentic-datacenter-ci-") as scratch:
                clone = Path(scratch) / "w"
                subprocess.run(
                    ["git", "clone", "--quiet", "--no-hardlinks", str(repo), str(clone)],
                    check=True,
                )
                done = subprocess.run(
                    ["docker", "run", "--rm", "-v", f"{clone}:/w", "-w", "/w",
                     "-e", "GITHUB_WORKSPACE=/w", "-e", "CI=true", job.image,
                     "bash", "-c", script],
                    stdout=out, stderr=subprocess.STDOUT, check=False,
                )  # fmt: skip
        else:
            done = subprocess.run(
                ["bash", "-c", script], cwd=repo, env=host_environment(job, repo),
                stdout=out, stderr=subprocess.STDOUT, check=False,
            )  # fmt: skip
    where = "the reference image" if docker else "the host"
    return Result(job.name, job.context, done.returncode == 0, time.monotonic() - start, where)


def statuses(results: list[Result]) -> list[dict[str, str]]:
    """Return one commit status per job name, from the results of its legs."""
    out = []
    for context in dict.fromkeys(r.context for r in results):
        legs = [r for r in results if r.context == context]
        failed = [r.name for r in legs if not r.passed]
        seconds = sum(r.seconds for r in legs)
        text = f"Run locally on {legs[0].where}, {seconds:.0f} s"
        if failed:
            text = f"Failed: {', '.join(failed)}. {text}"
        out.append(
            {
                "context": context,
                "state": "failure" if failed else "success",
                "description": text[:140],
            }
        )
    return out


def publishable(dirty: bool, pushed: bool) -> None:
    """Exit unless the commit is exactly what was tested and GitHub has it."""
    if dirty:
        sys.exit("not publishing: there are uncommitted changes, so the run is not of a commit")
    if not pushed:
        sys.exit("not publishing: the commit is not pushed, so GitHub has nothing to attach to")


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def main(argv: list[str] | None = None) -> int:
    """Run the chosen jobs and report."""
    parser = argparse.ArgumentParser(description="Run a workflow of this repository locally.")
    parser.add_argument("--workflow", default="pr", help="Name of a file in .github/workflows.")
    parser.add_argument("--job", action="append", help="Run only this job; repeat for several.")
    parser.add_argument("--docker", action="store_true", help="Run inside the workflow's image.")
    parser.add_argument("--publish", action="store_true", help="Report commit statuses to GitHub.")
    parser.add_argument("--list", action="store_true", help="Print the plan and stop.")
    args = parser.parse_args(argv)

    jobs = plan(REPO / ".github/workflows" / f"{args.workflow}.yml", args.docker)
    if args.job:
        unknown = set(args.job) - {j.context for j in jobs}
        if unknown:
            sys.exit(f"no such job: {', '.join(sorted(unknown))}")
        jobs = [j for j in jobs if j.context in args.job]
    if args.list:
        for job in jobs:
            print(job.name)
            for command in job.commands:
                print(f"    {command}")
        return 0
    if args.docker and shutil.which("docker") is None:
        sys.exit("--docker needs a container runtime on PATH")
    sha = _git(REPO, "rev-parse", "HEAD")
    dirty = bool(_git(REPO, "status", "--porcelain"))
    if args.publish:
        pushed = bool(_git(REPO, "branch", "-r", "--contains", sha))
        publishable(dirty, pushed)
    logs = REPO / "build/ci" / sha[:12]
    logs.mkdir(parents=True, exist_ok=True)
    results = []
    for job in jobs:
        slug = re.sub(r"[^a-z0-9]+", "-", job.name.lower()).strip("-")
        print(f"{job.name} ...", end=" ", flush=True)
        result = _run(job, REPO, args.docker, logs / f"{slug}.log")
        print(f"{'ok' if result.passed else 'FAILED'} ({result.seconds:.0f} s)")
        results.append(result)
    summary = {
        "commit": sha, "dirty": dirty, "workflow": args.workflow,
        "results": [asdict(r) for r in results],
    }  # fmt: skip
    (logs / f"{args.workflow}.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(f"logs: {logs}")
    if args.publish:
        remote = _git(REPO, "remote", "get-url", "origin")
        slug = re.sub(r"^.*github\.com[:/]|\.git$", "", remote)
        for status in statuses(results):
            subprocess.run(
                ["gh", "api", "-X", "POST", f"repos/{slug}/statuses/{sha}", "--silent",
                 *(arg for k, v in status.items() for arg in ("-f", f"{k}={v}"))],
                check=True,
            )  # fmt: skip
        print(f"published {len(statuses(results))} commit status(es) for {sha[:12]}")
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
