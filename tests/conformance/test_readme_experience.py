"""The README as the front door (SDD-ADC-002): order, buttons, honest labels, working links."""

import hashlib
import json
import re
import xml.dom.minidom
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
README = (REPO / "README.md").read_text(encoding="utf-8")
BUTTONS = REPO / "docs/media/buttons"
ROUTES = {
    "demo.svg": "docs/demo/result-report.md",
    "datacenter.svg": "docs/guides/bring-your-own-datacenter.md",
    "equipment.svg": "equipment/README.md",
    "agent.svg": "docs/guides/bring-your-own-agent.md",
    "governance.svg": "docs/guides/bring-your-own-gate.md",
}
#: The animation and the video of the hero, as they were when SDD-ADC-002 was written.
MEDIA = {
    "docs/media/agentic_datacenter_visual.webp": (
        "d3acf53048c9fdcc79c70f3e5e92e039189ff1bb47178b9746ed8753b5de1718"
    ),
    "docs/media/agentic_datacenter_visual.mp4": (
        "787ed2a66da008a6a9fb23bff727ea204e3af028d93e0200b55ff4023f03eafc"
    ),
}


def _links(text: str) -> list[str]:
    markdown = re.findall(r"\]\(([^)\s]+)\)", text)
    html = re.findall(r'(?:href|src)="([^"]+)"', text)
    return markdown + html


@pytest.mark.req("ADC-UX-001")
def test_the_hero_states_the_purpose_then_one_demo_then_four_roles_then_the_media() -> None:
    lines = README.splitlines()
    assert lines[0] == "# Agentic-Datacenter"
    assert "**Test autonomous operations before they reach production.**" in lines[:4]
    hero = README.split("## ", 1)[0]
    order = [hero.index(f"docs/media/buttons/{b}") for b in ROUTES]
    assert order == sorted(order), "demo, datacenter, equipment, agent, governance"
    assert hero.index("buttons/governance.svg") < hero.index("agentic_datacenter_visual.webp")
    targets = re.findall(r'<a href="([^"]+)"><img src="docs/media/buttons/', hero)
    assert len(targets) == len(set(targets)) == 5


@pytest.mark.req("ADC-UX-002")
@pytest.mark.parametrize("button", sorted(ROUTES))
def test_each_button_is_a_static_local_svg_linked_to_its_real_destination(button: str) -> None:
    path = BUTTONS / button
    text = path.read_text(encoding="utf-8")
    xml.dom.minidom.parseString(text)  # well formed
    assert path.stat().st_size <= 10 * 1024
    for active in ("<script", "foreignObject", "href=", "on" + "load", "onclick", "@import",
                   "<animate", "url(", "<image"):  # fmt: skip
        assert active not in text, (button, active)
    assert re.search(r'viewBox="0 0 \d+ \d+"', text)
    anchor = re.search(
        rf'<a href="([^"]+)"><img src="docs/media/buttons/{button}" alt="([^"]+)"', README
    )
    assert anchor, button
    assert anchor.group(1) == ROUTES[button]
    assert (REPO / anchor.group(1)).is_file()
    assert len(anchor.group(2)) > 10


@pytest.mark.req("ADC-UX-003")
def test_the_animation_and_the_video_are_kept_and_labelled_illustrative() -> None:
    for path, digest in MEDIA.items():
        assert hashlib.sha256((REPO / path).read_bytes()).hexdigest() == digest, path
    assert 'href="docs/media/agentic_datacenter_visual.mp4"' in README
    assert "Illustrative" in README.split("## ", 1)[0]


@pytest.mark.req("ADC-UX-005")
def test_the_demo_opens_a_markdown_report_with_its_label() -> None:
    report = (REPO / ROUTES["demo.svg"]).read_text(encoding="utf-8")
    assert "*development run, not a benchmark result.*" in report


@pytest.mark.req("ADC-UX-008")
def test_the_agent_path_says_it_is_planned_everywhere_it_is_offered() -> None:
    svg = (BUTTONS / "agent.svg").read_text(encoding="utf-8")
    assert "Roadmap" in svg
    alt = re.search(r'buttons/agent.svg" alt="([^"]+)"', README)
    assert alt and "planned" in alt.group(1)
    guide = (REPO / ROUTES["agent.svg"]).read_text(encoding="utf-8")
    first = guide.split("\n\n")[1]
    assert "planned" in first and "scripted agents" in first
    assert "uv run" not in guide.split("## What exists today", 1)[0]


@pytest.mark.req("ADC-UX-010")
@pytest.mark.parametrize(
    "document", ["README.md", "docs/guides/bring-your-own-agent.md", "equipment/README.md"]
)
def test_every_local_link_and_image_resolves(document: str) -> None:
    source = REPO / document
    for link in _links(source.read_text(encoding="utf-8")):
        if link.startswith(("http://", "https://", "mailto:", "#")):
            continue
        target = (source.parent / link.split("#", 1)[0]).resolve()
        assert target.exists(), f"{document}: {link}"


@pytest.mark.req("ADC-UX-011")
def test_the_result_in_the_readme_is_the_one_the_report_records() -> None:
    report = (REPO / "docs/demo/result-report.md").read_text(encoding="utf-8")
    recorded = re.search(
        r"harmed in (\d+) of (\d+) scenarios\. With (\S+) it was harmed in (\d+) of (\d+)", report
    )
    assert recorded
    no_gate, total, gate, with_gate, _ = recorded.groups()
    assert f"{no_gate} of {total} scenarios without a safety control" in README
    assert f"{with_gate} of {total}" in README and "development run" in README
    assert "not a benchmark result" in README


@pytest.mark.req("ADC-UX-012")
def test_licence_safety_and_commercial_boundaries_are_linked() -> None:
    trust = README.split("## Trust and licensing", 1)[1]
    for target in ("LICENSE", "COMMERCIAL_LICENSING.md", "THIRD_PARTY_NOTICES.md", "SECURITY.md"):
        assert f"]({target})" in trust or f"]({target}" in README, target
    assert "Simulation only" in trust
    assert "never buy a benchmark result" in trust


@pytest.mark.req("ADC-UX-014")
def test_the_hero_names_no_date_season_or_count_that_will_go_stale() -> None:
    hero = README.split("## Try it locally", 1)[0]
    seasons = json.loads((REPO / "docs/bench/seasons.json").read_text(encoding="utf-8"))
    assert str(seasons.get("first_deadline", "2027"))[:4] not in hero
    assert not re.search(r"\bSeason \d", hero)
    assert not re.search(r"\b\d{2,} scenarios\b", hero), "a library count goes stale"


@pytest.mark.req("ADC-UX-001")
def test_the_readme_stays_short() -> None:
    text = re.sub(r"```.*?```", "", README, flags=re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\]\([^)]*\)", "]", text)
    assert len(re.findall(r"[A-Za-z][A-Za-z'’-]*", text)) <= 500
