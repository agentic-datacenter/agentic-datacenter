"""One scenario for each Monday, sealed before it is shown (ADR 0046).

The register holds the hash of every sealed file; a released file must be the
one that was sealed, sealed in time, short, and outside the frozen library.
"""

from __future__ import annotations

import copy
import importlib.util
from datetime import date
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("weekly", REPO / "tools/weekly.py")
assert _spec and _spec.loader
weekly = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(weekly)

SCENARIO = {
    "schema_version": 1, "id": "WK-01", "title": "t", "track": "C", "duration_s": 3600,
    "decision_every_s": 300, "objective": "resilience", "timeline": [], "pass_criteria": [],
    "expected": "e",
}  # fmt: skip


def _sealed(tmp_path: Path, **changes: object) -> tuple[dict, Path, Path]:  # type: ignore[type-arg]
    """Return a register with one sealed scenario, its kept-back file, and the release folder."""
    kept = tmp_path / "kept"
    kept.mkdir()
    file = kept / "WK-01.yaml"
    file.write_text(yaml.safe_dump({**SCENARIO, **changes}), encoding="utf-8")
    entry = weekly.entry_for(
        file, date(2026, 11, 30), date(2026, 11, 27), 1, family="authority", proposer="project"
    )
    return {"schema": weekly.SCHEMA, "entries": [entry]}, file, tmp_path / "scenarios"


@pytest.mark.req("ADC-BEN-010")
def test_the_register_and_the_released_files_agree() -> None:
    data = weekly.load()
    assert weekly.problems(data) == []
    assert [e["id"] for e in data["entries"]][:2] == ["WK-01", "WK-02"]
    assert all(date.fromisoformat(e["release_on"]).weekday() == 0 for e in data["entries"])


@pytest.mark.req("ADC-BEN-010")
def test_a_sealed_file_is_not_in_the_repository_before_its_monday() -> None:
    data = weekly.load()
    for entry in data["entries"]:
        there = (weekly.SCENARIOS / f"{entry['id']}.yaml").exists()
        assert there == (entry["status"] == "released"), entry["id"]


@pytest.mark.req("ADC-BEN-010")
def test_a_released_file_is_the_one_that_was_sealed(tmp_path: Path) -> None:
    data, file, folder = _sealed(tmp_path)
    folder.mkdir()
    assert weekly.problems(data, folder) == []
    data["entries"][0]["status"] = "released"
    assert "is missing" in weekly.problems(data, folder)[0]
    (folder / "WK-01.yaml").write_bytes(file.read_bytes())
    assert weekly.problems(data, folder) == []
    (folder / "WK-01.yaml").write_text(file.read_text("utf-8") + "# changed\n", encoding="utf-8")
    assert weekly.problems(data, folder) == ["WK-01: the file is not the one that was sealed"]


@pytest.mark.req("ADC-BEN-010")
def test_a_scenario_sealed_late_or_shown_early_is_refused(tmp_path: Path) -> None:
    data, file, folder = _sealed(tmp_path)
    folder.mkdir()
    late = copy.deepcopy(data)
    late["entries"][0]["sealed_on"] = "2026-11-28"
    assert "less than 3 days before" in weekly.problems(late, folder)[0]
    (folder / "WK-01.yaml").write_bytes(file.read_bytes())
    assert "it is sealed, not released" in weekly.problems(data, folder)[0]
    (folder / "WK-09.yaml").write_text("id: WK-09\n", encoding="utf-8")
    assert any("with no entry in the register" in p for p in weekly.problems(data, folder))
    midweek = copy.deepcopy(data)
    midweek["entries"][0]["release_on"] = "2026-12-01"
    assert any("must be a Monday" in p for p in weekly.problems(midweek, tmp_path / "none"))


@pytest.mark.req("ADC-BEN-010")
def test_a_weekly_scenario_is_short(tmp_path: Path) -> None:
    """Nothing that plays out over a day: at most two simulated hours."""
    assert weekly.MAX_DURATION_S == 7200
    assert weekly.too_long({"duration_s": 7200}) == ""
    assert "at most 2 simulated hours" in weekly.too_long({"duration_s": 111600})
    with pytest.raises(ValueError, match="at most 2 simulated hours"):
        _sealed(tmp_path, duration_s=111600)


@pytest.mark.req("ADC-BEN-010")
def test_a_missed_monday_and_an_unsealed_week_are_said(tmp_path: Path) -> None:
    data, _, _ = _sealed(tmp_path)
    assert weekly.due(data, date(2026, 11, 27)) == []
    monday = weekly.due(data, date(2026, 11, 30))
    assert any("WK-01 was to be released on 2026-11-30" in line for line in monday)
    assert any("no scenario is in the register for Monday 2026-12-07" in line for line in monday)
    data["entries"][0]["status"] = "released"
    data["entries"].append(
        {"id": "WK-02", "release_on": "2026-12-07", "status": "planned", "family": "authority",
         "proposer": "someone"}
    )  # fmt: skip
    assert weekly.due(data, date(2026, 12, 1)) == [
        "WK-02 for Monday 2026-12-07 is planned and not sealed; it must be sealed by 2026-12-04."
    ]
    assert "move it a week" in weekly.due(data, date(2026, 12, 5))[0]


@pytest.mark.req("ADC-BEN-010")
def test_weekly_scenarios_are_outside_the_frozen_library() -> None:
    from agentic_datacenter.scenarios.scenario import library_ids

    assert not [name for name in library_ids() if name.startswith("WK-")]
    page = (REPO / "docs/bench/WEEKLY.md").read_text(encoding="utf-8")
    assert "At most two simulated hours" in page and "Sealed before it is shown" in page
    template = (REPO / "examples/ci/agentic-datacenter.yml").read_text(encoding="utf-8")
    assert "weekly/scenarios/WK-*.yaml" in template
    for entry in weekly.load()["entries"]:
        assert f"`{entry['id']}`" in page, "the page lists every week of the register"
