"""A governance system is named only after it enrolled itself; then its results stand beside others.

The table of enrolled systems, its entries, and the findings shared with their
maintainers first (ADR 0036).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("participants", REPO / "tools/participants.py")
assert _spec and _spec.loader
participants = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(participants)

CARD: dict[str, Any] = {
    "results": [
        {"gate": "their_gate", "agent": "scripted_adversarial", "unsafe_execution_rate": 0.0,
         "false_block_rate": 0.25, "safety": 1.0, "approvals_per_24h": 3.0},
        {"gate": "static_allowlist", "agent": "scripted_adversarial",
         "unsafe_execution_rate": 0.5, "false_block_rate": 0.0, "safety": 0.5,
         "approvals_per_24h": 0.0},
    ]
}  # fmt: skip


def _entry(**changes: Any) -> dict[str, Any]:
    entry: dict[str, Any] = {
        "id": "their-gate", "name": "Their Gate", "gate": "their_gate", "version": "a" * 40,
        "connection": "command_gate", "relation": "independent",
        "provides": ["decisions", "findings"],
        "capabilities": {"allow_deny": "uses", "verifies_mandates": "partial"},
        "enrolled": {"issue": "https://github.com/agentic-datacenter/agentic-datacenter/issues/77",
                     "date": "2026-12-01", "listing_consent": True},
        "results": [{"card": "card.json", "agentic_datacenter": "benchmark-v1.1",
                     "kind": "verified"}],
        "findings": [
            {"id": "F-001", "scenario": "AD-04", "seen_in": "benchmark-v1.1",
             "summary": "A decision reference was accepted twice.", "status": "fixed",
             "fixed_in": "b" * 40, "disclosed": "2026-12-20"},
            {"id": "F-002", "scenario": "AD-07", "seen_in": "benchmark-v1.1",
             "summary": "Not yet to be told.", "status": "reported_privately"},
        ],
    }  # fmt: skip
    entry.update(changes)
    return entry


def _write(tmp_path: Path, entry: dict[str, Any]) -> tuple[Path, Path]:
    entries = tmp_path / "participants"
    entries.mkdir(exist_ok=True)
    (entries / f"{entry['id']}.yaml").write_text(yaml.safe_dump(entry))
    (tmp_path / "card.json").write_text(json.dumps(CARD))
    return entries, tmp_path


@pytest.mark.req("ADC-INT-010")
def test_the_page_is_up_to_date_and_names_no_one_who_has_not_enrolled() -> None:
    assert participants.main(["--check"]) == 0
    entries, problems = participants.load()
    assert not problems
    page = (REPO / "docs/bench/participants.md").read_text(encoding="utf-8")
    if not entries:
        assert "No system has enrolled yet." in page


@pytest.mark.req("ADC-INT-010")
@pytest.mark.parametrize(
    ("changes", "problem"),
    [
        ({"enrolled": {"issue": "https://example.org/1", "listing_consent": True}}, "issue"),
        ({"enrolled": {"issue": "https://github.com/agentic-datacenter/agentic-datacenter/issues/9",
                       "listing_consent": False}}, "no consent, no name"),
        ({"relation": "friend"}, "relation"),
        ({"results": [{"card": "missing.json", "agentic_datacenter": "x", "kind": "verified"}]},
         "no card"),
        ({"findings": [{"id": "F-9", "status": "open"}]}, "without a disclosed date"),
    ],
)  # fmt: skip
def test_an_entry_without_its_own_enrollment_or_consent_is_refused(
    tmp_path: Path, changes: dict[str, Any], problem: str
) -> None:
    entries, repo = _write(tmp_path, _entry(**changes))
    _, problems = participants.load(entries, repo)
    assert any(problem in p for p in problems), problems


@pytest.mark.req("ADC-INT-010")
def test_results_stand_beside_the_built_in_gates_and_private_findings_are_only_counted(
    tmp_path: Path,
) -> None:
    entries, repo = _write(tmp_path, _entry())
    found, problems = participants.load(entries, repo)
    assert not problems
    page = participants.render(found, repo)
    assert (
        "[Their Gate](https://github.com/agentic-datacenter/agentic-datacenter/issues/77)" in page
    )
    assert "| `scripted_adversarial` | 0 % | 25 % | 100 % | 3.0 |" in page
    assert "beside it: `static_allowlist` (reference control)" in page
    assert "A decision reference was accepted twice." in page
    assert "Not yet to be told." not in page
    assert "Reported to maintainers and not yet published: 1." in page


@pytest.mark.req("ADC-INT-010")
def test_the_registration_form_asks_for_consent_to_be_named() -> None:
    form = yaml.safe_load((REPO / ".github/ISSUE_TEMPLATE/gate-registration.yml").read_text())
    listing = next(b for b in form["body"] if b.get("id") == "listing")
    assert listing["type"] == "checkboxes"
    assert "docs/bench/participants.md" in listing["attributes"]["options"][0]["label"]
    assert "sent to you first" in listing["attributes"]["description"]


@pytest.mark.req("ADC-INT-010")
def test_every_system_says_what_it_brings_and_uses_and_the_page_shows_it(tmp_path: Path) -> None:
    (tmp_path / "card.json").write_text(json.dumps(CARD), encoding="utf-8")
    entry = _entry()
    assert participants._problems(entry, "their-gate", tmp_path) == []
    for changes, problem in (
        ({"provides": []}, "provides must list"),
        ({"provides": ["opinions"]}, "provides must list"),
        ({"capabilities": {"reads_minds": "uses"}}, "capabilities may name only"),
        ({"capabilities": {"allow_deny": "sometimes"}}, "a capability is one of"),
    ):
        found = participants._problems(_entry(**changes), "their-gate", tmp_path)
        assert any(problem in p for p in found), changes
    page = participants.render([entry], tmp_path)
    assert "| [Their Gate](" in page and "| independent | decisions, findings |" in page
    assert "| Verifies signed mandates | partly |" in page and "| Allows and denies | yes |" in page
    assert "| Signs its receipts |  |" in page  # not stated is not a no
    assert "(reference control)" in page and "remora" not in page.lower()


@pytest.mark.req("ADC-INT-010")
def test_a_system_of_this_projects_authors_is_enrolled_and_listed_like_any_other() -> None:
    entries, problems = participants.load()
    assert not problems
    (remora,) = [e for e in entries if e["id"] == "remora"]
    assert remora["relation"] == "benchmark_authors"
    assert remora["enrolled"]["listing_consent"] is True
    pin = (REPO / "REMORA_PIN").read_text(encoding="utf-8")
    assert remora["version"] in pin
    assert not set(participants.BUILT_IN) & {"remora", "remora_governed", "remora_shadow"}
    assert [e["name"] for e in entries] == sorted(e["name"] for e in entries)
    readme = (REPO / "README.md").read_text(encoding="utf-8")
    assert "REMORA" not in readme.split("## Trust and licensing")[0]
