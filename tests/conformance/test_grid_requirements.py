"""A facility is tried against a system operator's connection requirements (ADR 0044).

Each file in ``grid/`` says where every value was read and whether it is in
force; the check plays its dips against the facility and never calls a time
met or not met when the model cannot tell.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.scenarios import cli, grid_check
from agentic_datacenter.scenarios.grid_check import MEASURED, MET, NOT_MET, TOO_CLOSE

REPO = Path(__file__).resolve().parents[2]
FILES = sorted((REPO / "grid").glob("*.yaml"))
NORWAY = REPO / "grid/no-nvf-2026-draft.yaml"


@pytest.fixture(scope="module")
def generic():
    return load_profile(REPO / "profiles/generic_dc.yaml")


@pytest.fixture(scope="module")
def norway(generic):
    return grid_check.check(grid_check.load_requirements(NORWAY), generic)


@pytest.mark.req("ADC-FAC-013")
@pytest.mark.parametrize("path", FILES, ids=lambda p: p.stem)
def test_every_file_says_where_it_was_read_and_whether_it_is_in_force(path: Path) -> None:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert grid_check.problems(data) == []
    assert data["id"] == path.stem
    assert data["status"] in grid_check.STATUSES
    assert data["source"]["url"].startswith("https://")
    assert data["not_checked"], "a file says what the model leaves out"


@pytest.mark.req("ADC-FAC-013")
def test_no_file_claims_to_be_in_force_today() -> None:
    """Nothing read so far is a rule in force; a file that says so needs its decision read."""
    assert len(FILES) >= 3
    assert {yaml.safe_load(p.read_text("utf-8"))["status"] for p in FILES} <= {
        "proposed", "recommended",
    }  # fmt: skip


@pytest.mark.req("ADC-FAC-013")
def test_a_file_without_a_source_cannot_be_used(tmp_path: Path) -> None:
    data = yaml.safe_load(NORWAY.read_text(encoding="utf-8"))
    del data["source"]
    data["status"] = "law"
    bad = tmp_path / "bad.yaml"
    bad.write_text(yaml.safe_dump(data), encoding="utf-8")
    with pytest.raises(ValueError, match="source must give") as error:
        grid_check.load_requirements(bad)
    assert "status must be one of" in str(error.value)


@pytest.mark.req("ADC-FAC-013")
def test_the_dips_tried_are_the_longest_the_curve_allows() -> None:
    curve = grid_check.load_requirements(NORWAY).curve
    assert curve is not None
    assert grid_check.curve_at(curve, 100) == 0.0
    assert grid_check.curve_at(curve, 150) == 0.35
    assert grid_check.curve_at(curve, 1500) == 0.9
    assert grid_check.dips_of(curve) == [
        (0.0, 100), (0.35, 500), (0.5, 800), (0.7, 1100), (0.85, 1400),
    ]  # fmt: skip
    for retained, ms in grid_check.dips_of(curve):
        assert all(retained >= grid_check.curve_at(curve, t) for t in range(0, ms + 1, 100))
        assert retained < grid_check.curve_at(curve, ms + 100)


@pytest.mark.req("ADC-FAC-013")
def test_the_generic_facility_against_the_norwegian_proposal(norway) -> None:
    """Its UPS goes to battery, and recharging keeps the draw above what it was for seconds."""
    assert norway["requirements"]["status"] == "proposed"
    assert norway["facility"]["draw_kw"] > norway["facility"]["it_kw"] > 0
    dips = {(d["retained_pu"], d["ms"]): d for d in norway["dips"]}
    assert len(dips) == 5
    for dip in dips.values():
        assert dip["on_battery"] and dip["it_lost_kwh"] == 0.0
        assert dip["highest_share_after"] > 1.05
    late = dips[(0.35, 500)]["levels"][0]
    assert late["verdict"] == NOT_MET and late["back_after_s"] > 1.0 + norway["model"]["delay_s"]
    assert norway["ramp"]["verdict"] == MEASURED and norway["ramp"]["limit_share_per_s"] is None
    assert norway["summary"][NOT_MET] == 4 and norway["summary"][MET] == 0


@pytest.mark.req("ADC-FAC-013")
def test_a_time_the_model_cannot_tell_is_reported_as_that(norway) -> None:
    """The shortest dip is back just after the limit, by less than the model's own delay."""
    delay = norway["model"]["delay_s"]
    level = next(d for d in norway["dips"] if d["ms"] == 100)["levels"][0]
    assert delay > 0
    assert level["within_s"] < level["back_after_s"] <= level["within_s"] + delay
    assert level["verdict"] == TOO_CLOSE
    assert grid_check._verdict(1.2, 1.0, 0.5) == TOO_CLOSE
    assert grid_check._verdict(1.6, 1.0, 0.5) == NOT_MET
    assert grid_check._verdict(1.0, 1.0, 0.5) == MET
    assert grid_check._verdict(None, 1.0, 0.5) == NOT_MET
    assert grid_check._verdict(0.3, None, 0.5) == MEASURED


@pytest.mark.req("ADC-FAC-013")
def test_a_changed_facility_gives_a_changed_result(generic) -> None:
    """A slower recharge keeps the draw inside the band; the change is named on the report."""
    slow = generic.with_param("electrical.ups", "recharge_fraction", 0.02)
    report = grid_check.check(
        grid_check.load_requirements(NORWAY), slow, ramp_limit=0.2,
        changed={"electrical.ups.recharge_fraction": 0.02},
    )  # fmt: skip
    assert report["facility"]["changed"] == {"electrical.ups.recharge_fraction": 0.02}
    assert report["summary"][NOT_MET] == 1 and report["summary"][MET] >= 4
    assert report["ramp"]["verdict"] == NOT_MET
    assert "Changed for this check: electrical.ups.recharge_fraction" in grid_check.render(report)


@pytest.mark.req("ADC-FAC-013")
def test_the_report_says_what_it_is_not(norway) -> None:
    text = grid_check.render(norway)
    assert "PROPOSED, not in force" in text
    assert "Not a statement of compliance" in text
    assert "Not checked, and why:" in text
    assert "no source impedance" in text
    for row in norway["not_checked"]:
        assert row["what"] in text


@pytest.mark.req("ADC-FAC-013")
def test_the_command_lists_and_checks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO)
    assert cli.grid(["list"]) == 0
    listed = capsys.readouterr().out
    assert all(path.stem in listed for path in FILES)

    out = tmp_path / "report.json"
    assert cli.grid(["check", "eu-entsoe-2025-position", "--json", str(out)]) == 0
    text = capsys.readouterr().out
    assert "RECOMMENDED, not law" in text and "No dip tried" in text
    report = json.loads(out.read_text(encoding="utf-8"))
    assert report["schema"] == grid_check.REPORT_SCHEMA
    assert [hold["verdict"] for hold in report["continuous"]] == [MET, MET]

    assert cli.grid(["check", "no-nvf-2026-draft", "--fail-on-unmet"]) == 1
    capsys.readouterr()
    assert cli.grid(["check", "no-such-country"]) == 2
    assert cli.grid(["check", "ie-mpid-345", "--dip", "0.5:250"]) == 2
    assert "multiple of 100" in capsys.readouterr().err
