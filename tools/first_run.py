"""Time the first run of every role, from a fresh clone, as a newcomer would do it (SDD-ADC-002).

    python tools/first_run.py [--repo <url or path>] [--ref <branch>] [--out build/first-run-times]

Clones the repository into an empty directory and runs, in order, the commands
the README and the role guides give. Each is timed, and none needs a
credential, an API key, privileged access or a network connection beyond the
clone and the package download (ADC-UX-013):

1. ``uv sync``
2. the README's demo
3. ``facility check`` of the example bundle (datacenter path)
4. ``equipment check`` of the maker's template (equipment path)
5. the example gate served over HTTP and ``gate check http_gate`` (governance path)

It writes ``first_run.json`` and ``first_run.md`` with the commands, the exit
status and the seconds of each step, the commit, the machine and the date. The
times are those of one machine on one day, not a promise.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import socket
import subprocess
import sys
import tempfile
import time  # noqa: TID251 -- a tool that times commands on the wall clock
from datetime import UTC, datetime
from pathlib import Path

STEPS: list[tuple[str, str]] = [
    ("Install", "uv sync"),
    (
        "Demo (README)",
        "uv run agentic-datacenter demo --scenario OP-03 --gate static_allowlist "
        "--out build/first-run",
    ),
    ("Datacenter path", "uv run agentic-datacenter facility check examples/byodc"),
    (
        "Equipment path",
        "uv run agentic-datacenter equipment check equipment/TEMPLATE.vendor.yaml "
        "--source equipment/TEMPLATE.source.yaml",
    ),
    ("Governance path", "uv run agentic-datacenter gate check http_gate"),
]


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def run(repo: str, ref: str | None, out: Path) -> dict[str, object]:
    """Clone *repo* and time every step; return the record."""
    work = Path(tempfile.mkdtemp(prefix="adc-first-run-"))
    clone = ["git", "clone", "--quiet", *(["--branch", ref] if ref else []), repo, str(work)]
    started = time.monotonic()
    subprocess.run(clone, check=True)
    record: dict[str, object] = {
        "date": datetime.now(UTC).isoformat(timespec="seconds"),  # noqa: TID251
        "commit": subprocess.run(
            ["git", "-C", str(work), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip(),  # fmt: skip
        "machine": f"{platform.system()} {platform.machine()}, Python {platform.python_version()}",
        "clone_s": round(time.monotonic() - started, 1),
        "steps": [],
    }
    port = _free_port()
    env = {
        **os.environ,
        "ADC_GATE_URL": f"http://127.0.0.1:{port}",
        "ADC_GATE_NAME": "example",
    }
    for key in [k for k in env if k.startswith(("ANTHROPIC_", "OPENAI_", "AWS_"))]:
        env.pop(key)  # no credential is needed, so none is offered
    server = None
    steps: list[dict[str, object]] = []
    try:
        for name, command in STEPS:
            if name == "Governance path":
                server = subprocess.Popen(
                    [sys.executable, "examples/http-gate/server.py", "--port", str(port)],
                    cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                )  # fmt: skip
                time.sleep(1.0)
            began = time.monotonic()
            done = subprocess.run(
                command, shell=True, cwd=work, env=env, capture_output=True, text=True
            )
            steps.append({
                "step": name, "command": command, "exit": done.returncode,
                "seconds": round(time.monotonic() - began, 1),
                "tail": (done.stdout + done.stderr).strip().splitlines()[-3:],
            })  # fmt: skip
    finally:
        if server is not None:
            server.terminate()
    record["steps"] = steps
    record["total_s"] = round(time.monotonic() - started, 1)
    out.mkdir(parents=True, exist_ok=True)
    (out / "first_run.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"# First run, measured {record['date']}",
        "",
        f"Commit `{record['commit']}` on {record['machine']}. Clone: {record['clone_s']} s. "
        f"Total: {record['total_s']} s. One machine on one day, not a promise.",
        "",
        "| Step | Command | Exit | Seconds |",
        "| --- | --- | ---: | ---: |",
    ]
    lines += [f"| {s['step']} | `{s['command']}` | {s['exit']} | {s['seconds']} |" for s in steps]
    (out / "first_run.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return record


def main(argv: list[str] | None = None) -> int:
    """Run and print the table; 1 if any step failed."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--repo", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--ref")
    parser.add_argument("--out", type=Path, default=Path("build/first-run-times"))
    args = parser.parse_args(argv)
    record = run(args.repo, args.ref, args.out)
    print((args.out / "first_run.md").read_text(encoding="utf-8"))
    steps = record["steps"]
    assert isinstance(steps, list)
    return 0 if all(s["exit"] == 0 for s in steps) else 1


if __name__ == "__main__":
    sys.exit(main())
