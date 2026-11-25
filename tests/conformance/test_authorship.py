"""No commit names an AI tool as its author, committer or co-author (CONTRIBUTING.md)."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
AI_TOOL = re.compile(
    r"anthropic|openai|claude|copilot|chatgpt|gemini|codex|cursor(?:\.sh|\s+agent)|devin",
    re.IGNORECASE,
)


FORMAT = "--format=%h%x1f%an <%ae>%x1f%cn <%ce>%x1f%(trailers)%x1e"


def _history() -> list[tuple[str, str]]:
    try:
        out = subprocess.run(
            ["git", "-C", str(REPO), "log", FORMAT],
            check=True, capture_output=True, text=True,
        ).stdout  # fmt: skip
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("no git history here")
    commits = []
    for record in filter(lambda r: r.strip("\n"), out.split("\x1e")):
        sha, author, committer, trailers = record.strip("\n").split("\x1f")
        names = [author, committer]
        names += [line for line in trailers.splitlines() if re.match(r"(?i)co-authored-by:", line)]
        commits.append((sha, "\n".join(names)))
    return commits


def test_no_commit_names_an_ai_tool_as_author_committer_or_co_author() -> None:
    offending = [f"{sha}: {names}" for sha, names in _history() if AI_TOOL.search(names)]
    assert not offending, "\n".join(offending)
