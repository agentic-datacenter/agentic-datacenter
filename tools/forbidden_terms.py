"""Add names that must never appear in the repository, and scan its whole history for them.

Each term is kept only as an HMAC-SHA-256 under a key that is not in the
repository (``tools/forbidden_terms.hmac``), so the names never reach the
repository and cannot be found by hashing a list of guesses (ADC-PRV-002).
The owner keeps the key on their own machine and as the Actions secret
``ADC_TERMS_KEY``:

    python tools/forbidden_terms.py init-key       # once: make the key, outside the repository
    python tools/forbidden_terms.py add            # type one term per line, then an empty line
    python tools/forbidden_terms.py scan-history   # every file in every commit, not only today's
    gh secret set ADC_TERMS_KEY < ~/.config/agentic-datacenter/forbidden-terms.key

The key is read from ``ADC_TERMS_KEY``, or else from the key file. A term is
one to three words. It is matched in lower case, word by word. A scan prints
where a forbidden term was found, never which term.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import hmac
import os
import re
import secrets  # noqa: TID251 - a key for the owner, not randomness in a simulation
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TERMS = REPO / "tools/forbidden_terms.hmac"
KEY_FILE = Path.home() / ".config/agentic-datacenter/forbidden-terms.key"
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".json", ".txt", ".html", ".svg", ""}
#: The list records which key its entries were made with, so a wrong key fails loudly.
KEY_LINE = "# key "


class TermsKeyError(Exception):
    """The key is missing, or is not the one the list was made with."""


def read_key(env: dict[str, str] | None = None, path: Path = KEY_FILE) -> bytes | None:
    """Return the key from ``ADC_TERMS_KEY`` or the key file, or None if there is none."""
    value = (env if env is not None else dict(os.environ)).get("ADC_TERMS_KEY", "").strip()
    if not value and path.is_file():
        value = path.read_text(encoding="utf-8").strip()
    return value.encode("utf-8") if value else None


def key_id(key: bytes) -> str:
    """Return a short name of *key* that does not show it."""
    return hmac.new(key, b"agentic-datacenter forbidden-terms key", hashlib.sha256).hexdigest()[:16]


def normalize(term: str) -> str | None:
    """Return *term* as it is hashed, or None if it is not one to three words."""
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", term.lower())
    return " ".join(words) if 1 <= len(words) <= 3 else None


def digest(key: bytes, term: str) -> str:
    """Return the keyed hash of a normalized term."""
    return hmac.new(key, term.encode("utf-8"), hashlib.sha256).hexdigest()


def hashed_words(key: bytes, text: str) -> set[str]:
    """Return the keyed hash of every run of one to three words in *text*."""
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", text.lower())
    grams = set(words) | {" ".join(p) for p in zip(words, words[1:], strict=False)}
    grams |= {" ".join(p) for p in zip(words, words[1:], words[2:], strict=False)}
    return {digest(key, g) for g in grams}


def listed_key_id(path: Path = TERMS) -> str | None:
    """Return the key name the list was made with, or None if it has none yet."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    return next(
        (line[len(KEY_LINE) :].strip() for line in lines if line.startswith(KEY_LINE)), None
    )


def known(path: Path = TERMS) -> set[str]:
    """Return the hashes already listed."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    return {line.split()[0] for line in lines if line.strip() and not line.startswith("#")}


def check_key(key: bytes | None, path: Path = TERMS) -> bytes:
    """Return *key* if the list can be read with it; raise if not."""
    if key is None:
        raise TermsKeyError(
            "no key: set ADC_TERMS_KEY or run `python tools/forbidden_terms.py init-key`"
        )
    listed = listed_key_id(path)
    if listed is not None and listed != key_id(key):
        raise TermsKeyError(
            f"the list was made with key {listed}, not with this key ({key_id(key)})"
        )
    return key


def add(terms: Iterable[str], key: bytes, path: Path = TERMS) -> int:
    """Append the keyed hash of each new term to *path*; return how many were added."""
    check_key(key, path)
    have = known(path)
    new = []
    for term in terms:
        normal = normalize(term)
        if normal is None:
            print("skipped a line that is not one to three words", file=sys.stderr)
            continue
        if digest(key, normal) not in have:
            have.add(digest(key, normal))
            new.append(digest(key, normal))
    with path.open("a", encoding="utf-8") as out:
        if listed_key_id(path) is None:
            out.write(f"{KEY_LINE}{key_id(key)}\n")
        out.writelines(f"{h}\n" for h in new)
    return len(new)


def scan_files(forbidden: set[str], key: bytes, repo: Path = REPO) -> list[str]:
    """Return every tracked text file of the current commit that holds a forbidden term."""
    tracked = subprocess.run(
        ["git", "-C", str(repo), "ls-files"], capture_output=True, text=True, check=True
    ).stdout.splitlines()
    hits = []
    for name in tracked:
        path = repo / name
        if path.suffix in TEXT_SUFFIXES and path.is_file():
            if forbidden & hashed_words(key, path.read_text(encoding="utf-8", errors="ignore")):
                hits.append(name)
    return hits


def scan_history(forbidden: set[str], key: bytes, repo: Path = REPO) -> list[str]:
    """Return ``blob path`` for every text file in any commit that holds a forbidden term."""
    git = ["git", "-C", str(repo)]
    listing = subprocess.run(
        [*git, "rev-list", "--all", "--objects"], check=True, capture_output=True, text=True
    ).stdout
    hits = []
    seen: set[str] = set()
    for line in listing.splitlines():
        sha, _, name = line.partition(" ")
        if not name or sha in seen or Path(name).suffix not in TEXT_SUFFIXES:
            continue
        seen.add(sha)
        kind = subprocess.run([*git, "cat-file", "-t", sha], capture_output=True, text=True)
        if kind.stdout.strip() != "blob":
            continue
        blob = subprocess.run([*git, "cat-file", "blob", sha], capture_output=True, check=True)
        if forbidden & hashed_words(key, blob.stdout.decode("utf-8", errors="ignore")):
            hits.append(f"{sha[:12]} {name}")
    # Commit messages are part of the history too.
    log = subprocess.run(
        [*git, "log", "--all", "--format=%h%x1f%B%x1e"], check=True, capture_output=True, text=True
    ).stdout
    for record in filter(str.strip, log.split("\x1e")):
        sha, _, message = record.strip("\n").partition("\x1f")
        if forbidden & hashed_words(key, message):
            hits.append(f"{sha} (commit message)")
    return hits


def init_key(path: Path = KEY_FILE) -> Path:
    """Write a new random key to *path*, readable by the owner only, unless one is there."""
    if not path.is_file():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600)
        path.write_text(secrets.token_hex(32) + "\n", encoding="utf-8")
    return path


def _read_terms() -> list[str]:
    print("One term per line; an empty line ends. Nothing you type is shown.", file=sys.stderr)
    terms = []
    while term := getpass.getpass("term: "):
        terms.append(term)
    return terms


def main(argv: Sequence[str] | None = None) -> int:
    """Run the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    actions = parser.add_subparsers(dest="action", required=True)
    actions.add_parser("init-key", help="Make the key, outside the repository.")
    actions.add_parser("add", help="Add terms, typed without being shown.")
    actions.add_parser("scan", help="Scan the files of the current commit.")
    actions.add_parser("scan-history", help="Scan every file and message of every commit.")
    args = parser.parse_args(argv)
    if args.action == "init-key":
        path = init_key()
        print(f"key {key_id(read_key(path=path) or b'')} in {path}")
        print(f"next: gh secret set ADC_TERMS_KEY < {path}")
        return 0
    try:
        key = check_key(read_key())
    except TermsKeyError as error:
        print(error, file=sys.stderr)
        return 2
    if args.action == "add":
        print(f"{add(_read_terms(), key)} term(s) added to {TERMS.relative_to(REPO)}")
        return 0
    forbidden = known()
    if not forbidden:
        print("no terms are listed yet; add them first (python tools/forbidden_terms.py add)")
        return 2
    hits = scan_files(forbidden, key) if args.action == "scan" else scan_history(forbidden, key)
    for hit in hits:
        print(f"forbidden term in {hit}")
    print(f"{len(forbidden)} term(s), {'no hits' if not hits else f'{len(hits)} hit(s)'}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
