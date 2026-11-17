"""Make the README figure from a demonstration page: one scenario, without a gate and with one.

    agentic-datacenter demo --scenario OP-03 --gate static_allowlist --out build/first-run
    python tools/readme_figure.py build/first-run/index.html docs/media/first-run.svg

The figure is the two charts of the first scenario on the page, side by side,
with the page's own styles inside it, so it renders as an image on GitHub in
light and dark mode. Nothing is drawn here that the page did not draw.
"""

from __future__ import annotations

import argparse
import html
import re
from pathlib import Path

CHART = 460, 220
TITLE_H = 28
GAP = 24


def figure(page: str) -> str:
    """Return a standalone SVG of the first scenario's two charts on *page*."""
    style = re.search(r"<style>(.*?)</style>", page, re.S)
    sides = re.findall(r"<h3>(.*?)</h3>(<svg.*?</svg>)", page, re.S)[:2]
    if style is None or len(sides) != 2:
        raise ValueError("the page has no styles, or fewer than two charts")
    # The page's own layout rules do not belong in a figure.
    css = re.sub(r"(?m)^\s*(body|svg)\s*\{[^}]*\}\s*$", "", style.group(1))
    width, height = 2 * CHART[0] + GAP, CHART[1] + TITLE_H
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" '
        f'width="{width}" height="{height}" font-family="system-ui, sans-serif">',
        f"<style>{css}\n.title {{ font-size: 13px; font-weight: 600; fill: var(--ink); }}\n"
        ".back { fill: var(--paper); }</style>",
        f'<rect class="back" width="{width}" height="{height}"/>',
    ]
    for index, (title, chart) in enumerate(sides):
        x = index * (CHART[0] + GAP)
        inner = re.sub(r"^<svg[^>]*>|</svg>$", "", chart.strip())
        parts.append(
            f'<text class="title" x="{x + 40}" y="18">{html.escape(html.unescape(title))}</text>'
            f'<svg x="{x}" y="{TITLE_H}" width="{CHART[0]}" height="{CHART[1]}" '
            f'viewBox="0 0 {CHART[0]} {CHART[1]}">{inner}</svg>'
        )
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> int:
    """Run the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("page", type=Path)
    parser.add_argument("out", type=Path)
    args = parser.parse_args()
    args.out.write_text(figure(args.page.read_text(encoding="utf-8")), encoding="utf-8")
    print(f"figure written to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
