r"""Make the committed example in ``docs/demo`` from a demonstration run.

    agentic-datacenter demo --gate remora_governed --out build/demo
    python tools/demo_example.py build/demo docs/demo

The committed example is a run with ``remora_governed``, which needs REMORA
installed (``uv sync --all-groups``).

The recording and the two pages are copied as the run wrote them, under the
names the documentation links to. The Markdown report is written from the
copied recording, with the picture of the page at its top and links to the
copies beside it. ``--check`` writes nothing and says whether the committed
reports are what the generator makes from the committed recording.

The picture, ``docs/media/result-report.png``, is a screenshot of
``docs/demo/result-report.html`` in light mode, taken with a headless browser
after the example is made, for instance:

    chromium --headless --hide-scrollbars --window-size=1012,1830 \
        --blink-settings=preferredColorScheme=1 \
        --screenshot=docs/media/result-report.png docs/demo/result-report.html
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from agentic_datacenter.scenarios.executive import render_executive, render_executive_markdown

#: Name in the example, and the file of a demonstration run it is a copy of.
COPIES = {
    "demo.json": "demo.json",
    "three-scenarios.html": "index.html",
    "result-report.html": "executive.html",
}
SCREENSHOT = "../media/result-report.png"


def reports(recording: Path) -> dict[str, str]:
    """Return the two reports of the example, by file name, from its *recording*."""
    demo = json.loads(recording.read_text(encoding="utf-8"))
    return {
        "result-report.html": render_executive(demo),
        "result-report.md": render_executive_markdown(
            demo,
            screenshot=SCREENSHOT,
            page="result-report.html",
            technical="three-scenarios.html",
        ),
    }


def stale(example: Path) -> list[str]:
    """Return the reports in *example* that differ from what its recording gives."""
    return [
        name
        for name, text in reports(example / "demo.json").items()
        if not (example / name).is_file() or (example / name).read_text(encoding="utf-8") != text
    ]


def main() -> int:
    """Run the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", type=Path, nargs="?", help="output directory of the demo command")
    parser.add_argument("example", type=Path, nargs="?", default=Path("docs/demo"))
    parser.add_argument("--check", action="store_true", help="compare, write nothing")
    args = parser.parse_args()
    if args.check:
        differing = stale(args.example)
        for name in differing:
            print(f"{args.example / name} is not what the generator makes", file=sys.stderr)
        return 1 if differing else 0
    if args.run is None:
        parser.error("the output directory of a demonstration run is required")
    args.example.mkdir(parents=True, exist_ok=True)
    for name, source in COPIES.items():
        (args.example / name).write_bytes((args.run / source).read_bytes())
    for name, text in reports(args.example / "demo.json").items():
        if name.endswith(".md"):
            (args.example / name).write_text(text, encoding="utf-8")
    print(f"example written to {args.example}")
    return 0 if not stale(args.example) else 1


if __name__ == "__main__":
    raise SystemExit(main())
