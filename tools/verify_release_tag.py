"""Check that a release tag is signed by a key the repository names.

The release workflow runs this before it installs or builds anything. It reads
the public keys from ``.github/release-signers/allowed_signers``, in the format
of ``ssh-keygen``'s allowed-signers file, and asks ``git verify-tag`` whether
the tag carries an SSH signature by one of them.

Usage: ``python tools/verify_release_tag.py v1.2.3 --commit <sha>``. With
``--signers-ref origin/main`` the keys are read from that branch and not from
the files of the checkout, so a tagged commit cannot bring a key of its own.
It needs ``git`` 2.34 or later and ``ssh-keygen``, and nothing outside the
standard library. The exit status is 0 when the signature verifies and 1 otherwise.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from collections.abc import Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SIGNERS_PATH = ".github/release-signers/allowed_signers"
SIGNERS = REPO / SIGNERS_PATH
SSH_SIGNATURE = "-----BEGIN SSH SIGNATURE-----"


def keys(signers: Path) -> list[str]:
    """Return the lines of *signers* that name a key: not blank, not a comment."""
    if not signers.is_file():
        return []
    lines = (line.strip() for line in signers.read_text(encoding="utf-8").splitlines())
    return [line for line in lines if line and not line.startswith("#")]


def _git(repo: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", str(repo), *arguments], capture_output=True, text=True, check=False
    )


def problem(
    tag: str, signers: Path, repo: Path, commit: str | None = None, where: str | None = None
) -> str | None:
    """Return why *tag* in *repo* is not to be released, or None when its signature verifies.

    With *commit*, the tag must also point at that commit, so that what was
    verified is what is built. *where* names the allowed-signers file in the
    messages, when *signers* is a copy of it.
    """
    where = where or str(signers)
    if not keys(signers):
        return (
            f"no release signing key is in {where}. Add the public SSH key that signs "
            "release tags to that file on the main branch, as its first lines describe, "
            "then run the release again."
        )
    ref = f"refs/tags/{tag}"
    kind = _git(repo, "cat-file", "-t", ref)
    if kind.returncode != 0:
        return f"there is no tag {tag} in this checkout: {kind.stderr.strip()}"
    if kind.stdout.strip() != "tag":
        return (
            f"{tag} is not an annotated tag, so it carries no signature. "
            f"Make it with `git tag -s {tag}`."
        )
    body = _git(repo, "cat-file", "tag", ref).stdout
    if SSH_SIGNATURE not in body:
        return (
            f"{tag} carries no SSH signature. This check accepts SSH signatures only "
            "(`git config gpg.format ssh`)."
        )
    if commit is not None:
        target = _git(repo, "rev-parse", f"{ref}^{{commit}}").stdout.strip()
        if target != commit:
            return f"{tag} points at {target}, not at the commit being built, {commit}"
    verified = _git(
        repo,
        "-c", "gpg.format=ssh",
        "-c", f"gpg.ssh.allowedSignersFile={signers.resolve()}",
        "verify-tag", ref,
    )  # fmt: skip
    if verified.returncode != 0:
        said = (verified.stderr or verified.stdout).strip()
        return f"the signature on {tag} is not by a key in {where}: {said}"
    return None


def main(argv: Sequence[str] | None = None) -> int:
    """Verify one tag and return the exit status."""
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("tag", help="The tag to verify, for example v1.2.3.")
    parser.add_argument("--signers", type=Path, default=SIGNERS, help="The allowed-signers file.")
    parser.add_argument(
        "--signers-ref",
        help=f"Read {SIGNERS_PATH} from this branch or commit, not from --signers.",
    )
    parser.add_argument("--commit", help="The commit the tag must point at.")
    parser.add_argument("--repo", type=Path, default=REPO, help="The checkout to look in.")
    args = parser.parse_args(argv)
    with tempfile.TemporaryDirectory() as scratch:
        signers, where = args.signers, str(args.signers)
        if args.signers_ref is not None:
            # A file that is not on that branch reads as one with no key in it.
            shown = _git(args.repo, "show", f"{args.signers_ref}:{SIGNERS_PATH}")
            signers = Path(scratch) / "allowed_signers"
            signers.write_text(shown.stdout if shown.returncode == 0 else "", encoding="utf-8")
            where = f"{SIGNERS_PATH} on {args.signers_ref}"
        found = problem(args.tag, signers, args.repo, args.commit, where)
    if found is not None:
        print(f"release tag not verified: {found}", file=sys.stderr)
        return 1
    print(f"{args.tag}: signed by a key in {where}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
