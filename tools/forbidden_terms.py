"""Add names that must never appear in the repository, and scan its whole history for them.

Only the SHA-256 of each term is kept (``tools/forbidden_terms.sha256``), so
the names themselves never reach the repository (ADC-PRV-002). The owner adds
them on their own machine, without them being shown or stored anywhere else:

    python tools/forbidden_terms.py add            # type one term per line, then an empty line
    python tools/forbidden_terms.py scan-history   # every file in every commit, not only today's

A term is one to three words. It is matched in lower case, word by word, as
the conformance test does on the files of the current commit. The scan prints
where a forbidden term was found, never which term.
"""

from __future__ import annotations

import argparse
import getpass
import hashlib
import re
import subprocess
import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
TERMS = REPO / "tools/forbidden_terms.sha256"
TEXT_SUFFIXES = {".py", ".md", ".yaml", ".yml", ".toml", ".json", ".txt", ".html", ".svg", ""}


def normalize(term: str) -> str | None:
    """Return *term* as it is hashed, or None if it is not one to three words."""
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", term.lower())
    return " ".join(words) if 1 <= len(words) <= 3 else None


def digest(term: str) -> str:
    """Return the hash of a normalized term."""
    return hashlib.sha256(term.encode("utf-8")).hexdigest()


def hashed_words(text: str) -> set[str]:
    """Return the hash of every run of one to three words in *text*."""
    words = re.findall(r"[A-Za-zÀ-ÿ0-9]+", text.lower())
    grams = set(words) | {" ".join(p) for p in zip(words, words[1:], strict=False)}
    grams |= {" ".join(p) for p in zip(words, words[1:], words[2:], strict=False)}
    return {digest(g) for g in grams}


def known(path: Path = TERMS) -> set[str]:
    """Return the hashes already listed."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    return {line.split()[0] for line in lines if line.strip() and not line.startswith("#")}


def add(terms: Iterable[str], path: Path = TERMS) -> int:
    """Append the hash of each new term to *path*; return how many were added."""
    have = known(path)
    new = []
    for term in terms:
        normal = normalize(term)
        if normal is None:
            print("skipped a line that is not one to three words", file=sys.stderr)
            continue
        if digest(normal) not in have:
            have.add(digest(normal))
            new.append(digest(normal))
    if new:
        with path.open("a", encoding="utf-8") as out:
            out.writelines(f"{h}\n" for h in new)
    return len(new)


def scan_history(forbidden: set[str], repo: Path = REPO) -> list[str]:
    """Return ``commit:path`` for every text file in any commit that holds a forbidden term."""
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
        if forbidden & hashed_words(blob.stdout.decode("utf-8", errors="ignore")):
            hits.append(f"{sha[:12]} {name}")
    return hits


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
    actions.add_parser("add", help="Add terms, typed without being shown.")
    actions.add_parser("scan-history", help="Scan every file of every commit.")
    args = parser.parse_args(argv)
    if args.action == "add":
        print(f"{add(_read_terms())} term(s) added to {TERMS.relative_to(REPO)}")
        return 0
    forbidden = known()
    if not forbidden:
        print("no terms are listed yet; add them first (python tools/forbidden_terms.py add)")
        return 2
    hits = scan_history(forbidden)
    for hit in hits:
        print(f"forbidden term in blob {hit}")
    print(f"{len(forbidden)} term(s), {'no hits' if not hits else f'{len(hits)} hit(s)'}")
    return 1 if hits else 0


if __name__ == "__main__":
    raise SystemExit(main())
