"""The release workflow verifies the tag's signature before it does anything else.

The check itself, ``tools/verify_release_tag.py``, is run here on tags made in
a scratch repository with keys made for the test.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
SIGNERS = REPO / ".github/release-signers/allowed_signers"
KEY_TYPES = ("ssh-ed25519", "ssh-rsa", "ecdsa-sha2-", "sk-ssh-ed25519@", "sk-ecdsa-sha2-")


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "verify_release_tag", REPO / "tools/verify_release_tag.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _steps() -> list[dict[str, object]]:
    text = (REPO / ".github/workflows/release.yml").read_text(encoding="utf-8")
    steps: list[dict[str, object]] = yaml.safe_load(text)["jobs"]["build"]["steps"]
    return steps


@pytest.mark.req("ADC-CI-005")
def test_the_release_verifies_the_tag_before_it_installs_or_builds() -> None:
    steps = _steps()
    runs = [str(step.get("run", "")) for step in steps]
    verify = next(i for i, run in enumerate(runs) if "tools/verify_release_tag.py" in run)
    assert '--commit "$GITHUB_SHA"' in runs[verify]
    # The keys come from the main branch: a tagged commit cannot bring its own.
    assert "--signers-ref" in runs[verify]
    assert "continue-on-error" not in steps[verify] and "if" not in steps[verify]
    assert "openssh-client" in runs[0], "ssh-keygen verifies the signature"
    before = steps[:verify]
    assert [("uses" in step) for step in before] == [False, True], "only git and the checkout"
    assert not any("uv " in run for run in runs[:verify])


def test_the_release_runs_the_suite_in_parallel_within_its_time_limit() -> None:
    text = (REPO / ".github/workflows/release.yml").read_text(encoding="utf-8")
    job = yaml.safe_load(text)["jobs"]["build"]
    assert "uv run pytest -n auto --dist loadfile" in [step.get("run") for step in job["steps"]]
    assert job["timeout-minutes"] >= 45


def test_the_file_of_release_signers_holds_public_keys_only() -> None:
    text = SIGNERS.read_text(encoding="utf-8")
    assert "PRIVATE KEY" not in text
    for line in _tool().keys(SIGNERS):
        assert any(f" {kind}" in line for kind in KEY_TYPES), line


def _git(repo: Path, *arguments: str) -> None:
    env = {
        **os.environ,
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_SYSTEM": os.devnull,
        "GIT_AUTHOR_NAME": "A Maintainer",
        "GIT_AUTHOR_EMAIL": "maintainer@example.org",
        "GIT_COMMITTER_NAME": "A Maintainer",
        "GIT_COMMITTER_EMAIL": "maintainer@example.org",
    }
    subprocess.run(["git", "-C", str(repo), *arguments], check=True, capture_output=True, env=env)


def _key(directory: Path, name: str) -> Path:
    path = directory / name
    subprocess.run(
        ["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", name, "-f", str(path)], check=True
    )
    return path


def _signers(path: Path, key: Path) -> Path:
    public = key.with_suffix(".pub").read_text(encoding="utf-8").split()
    path.write_text(
        f'# a comment\nmaintainer@example.org namespaces="git" {public[0]} {public[1]}\n',
        encoding="utf-8",
    )
    return path


@pytest.mark.req("ADC-CI-005")
@pytest.mark.skipif(
    shutil.which("git") is None or shutil.which("ssh-keygen") is None,
    reason="needs git and ssh-keygen",
)
def test_only_a_tag_signed_by_a_listed_key_verifies(tmp_path: Path) -> None:
    tool = _tool()
    repo = tmp_path / "repo"
    repo.mkdir()
    ours, other = _key(tmp_path, "ours"), _key(tmp_path, "other")
    _git(repo, "init", "-q")
    _git(repo, "commit", "-q", "--allow-empty", "-m", "first")
    signed = ("-c", "gpg.format=ssh", "-c", f"user.signingkey={ours}.pub")
    _git(repo, *signed, "tag", "-s", "-m", "release", "v1.0.0")
    _git(repo, "-c", "gpg.format=ssh", "-c", f"user.signingkey={other}.pub",
         "tag", "-s", "-m", "release", "v1.0.1")  # fmt: skip
    _git(repo, "tag", "-a", "-m", "release", "v1.0.2")
    _git(repo, "tag", "v1.0.3")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout.strip()
    signers = _signers(tmp_path / "allowed_signers", ours)

    assert tool.problem("v1.0.0", signers, repo, commit=head) is None
    assert tool.main(["v1.0.0", "--signers", str(signers), "--repo", str(repo)]) == 0
    assert "not by a key in" in tool.problem("v1.0.1", signers, repo)
    assert "carries no SSH signature" in tool.problem("v1.0.2", signers, repo)
    assert "not an annotated tag" in tool.problem("v1.0.3", signers, repo)
    assert "there is no tag" in tool.problem("v9.9.9", signers, repo)
    assert "not at the commit being built" in tool.problem("v1.0.0", signers, repo, "0" * 40)
    assert tool.main(["v1.0.1", "--signers", str(signers), "--repo", str(repo)]) == 1

    # A key for another purpose than git does not sign a release.
    public = ours.with_suffix(".pub").read_text(encoding="utf-8").split()
    elsewhere = tmp_path / "file_signers"
    elsewhere.write_text(
        f'maintainer@example.org namespaces="file" {public[0]} {public[1]}\n', encoding="utf-8"
    )
    assert "not by a key in" in tool.problem("v1.0.0", elsewhere, repo)


@pytest.mark.req("ADC-CI-005")
@pytest.mark.skipif(shutil.which("git") is None, reason="needs git")
def test_a_release_fails_with_a_plain_message_while_no_key_is_listed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    tool = _tool()
    empty = tmp_path / "allowed_signers"
    empty.write_text("# no key yet\n\n", encoding="utf-8")
    for signers in (empty, tmp_path / "absent"):
        found = tool.problem("v1.0.0", signers, tmp_path)
        assert found is not None and "no release signing key is in" in found
    # Read from a branch that does not hold the file, as before the file reached main.
    _git(tmp_path, "init", "-q")
    _git(tmp_path, "commit", "-q", "--allow-empty", "-m", "first")
    assert tool.main(["v1.0.0", "--repo", str(tmp_path), "--signers-ref", "HEAD"]) == 1
    said = capsys.readouterr().err
    assert "no release signing key is in .github/release-signers/allowed_signers on HEAD" in said
