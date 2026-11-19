"""The example gates are free to copy; a gate of your own is yours (issue 31)."""

from __future__ import annotations

import tomllib
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
EXAMPLES = REPO / "examples"


def test_the_examples_carry_the_mit_licence_of_the_same_copyright_holder() -> None:
    text = (EXAMPLES / "LICENSE").read_text(encoding="utf-8")
    assert text.startswith("MIT License\n")
    assert "Permission is hereby granted, free of charge" in text
    root = (REPO / "LICENSE").read_text(encoding="utf-8")
    holder = root.split("The Licensed Work is Copyright (C) 2026 ", 1)[1].split(".", 1)[0]
    assert f"Copyright (c) 2026 {holder}" in text


def test_every_example_file_says_which_licence_it_is_under() -> None:
    sources = sorted(EXAMPLES.rglob("*.py"))
    assert len(sources) >= 3
    for path in sources:
        assert "SPDX-License-Identifier: MIT" in path.read_text(encoding="utf-8"), path
    project = tomllib.loads((EXAMPLES / "python-gate/pyproject.toml").read_text("utf-8"))
    assert project["project"]["license"] == "MIT"
    assert (EXAMPLES / "python-gate/LICENSE").read_text("utf-8") == (
        EXAMPLES / "LICENSE"
    ).read_text("utf-8")


def test_the_repository_licence_is_unchanged_and_already_excepts_such_a_directory() -> None:
    root = (REPO / "LICENSE").read_text(encoding="utf-8")
    assert root.startswith("Business Source License 1.1")
    assert "explicitly state a\ndifferent license" in root


def test_the_guide_says_whose_a_gate_is_and_when_the_contribution_terms_apply() -> None:
    guide = (REPO / "docs/guides/bring-your-own-gate.md").read_text(encoding="utf-8")
    section = guide.split("## Licence", 1)[1]
    for words in (
        "A gate you wrote yourself is yours",
        "MIT",
        "examples/LICENSE",
        "not production use",
        "only to a change you ask to have merged into this repository",
    ):
        assert words in section, words
    contributing = (REPO / "CONTRIBUTING.md").read_text(encoding="utf-8")
    assert "A gate kept in a repository of your own" in contributing
    notices = (REPO / "THIRD_PARTY_NOTICES.md").read_text(encoding="utf-8")
    assert "`examples/`" in notices and "MIT" in notices
