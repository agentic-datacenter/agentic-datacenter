"""Check that every built wheel and source distribution holds the text of its licence.

The Business Source License asks for its text on each copy, and the GPL for a
copy of itself, so a distribution without the file is not to be released.
Usage: ``python tools/check_dist_licences.py dist/`` after ``uv build --all-packages``.
"""

from __future__ import annotations

import sys
import tarfile
import tomllib
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def expected() -> dict[str, str]:
    """Return the licence text each distribution must hold, by normalised name."""
    out = {}
    for project in sorted((REPO / "packages").glob("*/pyproject.toml")):
        name = tomllib.loads(project.read_text(encoding="utf-8"))["project"]["name"]
        out[name.replace("-", "_")] = (project.parent / "LICENSE").read_text(encoding="utf-8")
    return out


def licence_texts(archive: Path) -> list[str]:
    """Return the text of every file named LICENSE in a wheel or a source distribution."""
    if archive.suffix == ".whl":
        with zipfile.ZipFile(archive) as wheel:
            names = [n for n in wheel.namelist() if n.rsplit("/", 1)[-1] == "LICENSE"]
            return [wheel.read(n).decode("utf-8") for n in names]
    with tarfile.open(archive) as sdist:
        members = [m for m in sdist.getmembers() if m.name.rsplit("/", 1)[-1] == "LICENSE"]
        return [sdist.extractfile(m).read().decode("utf-8") for m in members]  # type: ignore[union-attr]


def problems(dist: Path) -> list[str]:
    """Return one line per distribution that is missing, or lacks its licence text."""
    wanted = expected()
    found = sorted(p for p in dist.iterdir() if p.suffix == ".whl" or p.name.endswith(".tar.gz"))
    out = []
    for name, text in wanted.items():
        mine = [p for p in found if p.name.split("-")[0] == name]
        kinds = {"wheel" if p.suffix == ".whl" else "sdist" for p in mine}
        out += [f"{name}: no {kind} in {dist}" for kind in ("wheel", "sdist") if kind not in kinds]
        out += [
            f"{p.name}: the licence text is missing" for p in mine if text not in licence_texts(p)
        ]
    out += [
        f"{p.name}: not a distribution of this repository"
        for p in found
        if p.name.split("-")[0] not in wanted
    ]
    return out


def main(argv: list[str]) -> int:
    """Return 0 when every distribution in the directory holds its licence text."""
    if len(argv) != 2:
        raise SystemExit("usage: check_dist_licences.py <directory of built distributions>")
    found = problems(Path(argv[1]))
    for line in found:
        print(line)
    if not found:
        print(f"{len(expected())} distributions, each wheel and sdist holds its licence text")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
