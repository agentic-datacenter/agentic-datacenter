"""Starting points for operators and makers (the adoption phase)."""

import json
import re
from pathlib import Path

import pytest
import yaml

from agentic_datacenter.core.facility import load_facility
from agentic_datacenter.scenarios.cli import equipment as equipment_cli
from agentic_datacenter.scenarios.cli import facility as facility_cli

REPO = Path(__file__).resolve().parents[2]


@pytest.mark.req("ADC-FAC-011")
def test_facility_init_starts_a_bundle_from_the_example(tmp_path: Path) -> None:
    target = tmp_path / "my-dc"
    assert facility_cli(["init", str(target)]) == 0
    own = load_facility(target)
    assert own.profile.hash() == load_facility(REPO / "examples/byodc").profile.hash()
    assert facility_cli(["init", str(target)]) == 1  # not into a directory with files


@pytest.mark.req("ADC-FAC-012")
@pytest.mark.req("ADC-AGT-002")
def test_facility_report_gives_an_operator_one_page(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "report"
    status = facility_cli(
        ["report", str(REPO / "examples/byodc"), "--gate", "static_allowlist", "--jobs", "2",
         "--out", str(out)]
    )  # fmt: skip
    assert status == 0
    # A line when it starts and one per finished run, so the terminal is never silent.
    said = capsys.readouterr().err.splitlines()
    assert "comparing static_allowlist" in said[0] and "2 run(s) at a time" in said[0]
    counted = [re.fullmatch(r"\[(\d+)/(\d+)\] \S.*", line) for line in said[1:]]
    assert all(counted), said
    total = int(counted[0].group(2))  # type: ignore[union-attr]
    assert [int(m.group(1)) for m in counted if m] == list(range(1, total + 1))
    page = (out / "operator_report.md").read_text(encoding="utf-8")
    check = json.loads((out / "facility_report.json").read_text(encoding="utf-8"))
    fit = len(check["fit"]["scenarios_run"])
    assert total == 3 * fit, "each scenario with two agents, and once with no agent"
    assert f"The table is made from all {fit} scenarios that fit, each run once" in page
    assert "result on a facility of its owner, not a benchmark result" in page
    assert "| `static_allowlist` | scripted_adversarial |" in page
    assert "**Agent:** Scripted agents: predefined, simulated calls (the default)." in page
    card = json.loads((out / "result_card.json").read_text(encoding="utf-8"))
    assert card["facility"]["name"] == "example_mixed_pods"
    assert (out / "facility_report.md").is_file() and (out / "report.html").is_file()


@pytest.mark.req("ADC-FAC-012")
def test_facility_report_on_chosen_scenarios_says_what_it_was_made_from(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "report"
    bundle = str(REPO / "examples/byodc")
    chosen = ["--scenario", "AD-02", "--scenario", "AD-08", "--scenario", "OP-06"]
    status = facility_cli(
        ["report", bundle, "--gate", "static_allowlist", *chosen, "--jobs", "1", "--out", str(out)]
    )
    assert status == 0
    said = capsys.readouterr().err.splitlines()
    assert "1 run(s) at a time" in said[0]
    assert [line.split("]")[0] for line in said[1:]] == [f"[{n}/6" for n in range(1, 7)]
    card = json.loads((out / "result_card.json").read_text(encoding="utf-8"))
    assert card["scenarios"] == ["AD-02", "AD-08"]  # OP-06 does not fit the example
    check = json.loads((out / "facility_report.json").read_text(encoding="utf-8"))
    fit = len(check["fit"]["scenarios_run"])
    assert fit > 2, "the facility check still covers the whole library"
    page = (out / "operator_report.md").read_text(encoding="utf-8")
    assert f"The table is made from 2 of the {fit} scenarios that fit (AD-02, AD-08)" in page
    # A scenario that does not fit leaves nothing to compare, and the command says so.
    assert facility_cli(["report", bundle, "--scenario", "OP-06", "--out", str(out)]) == 1
    assert "no chosen scenario fits this facility" in capsys.readouterr().err
    assert facility_cli(["report", bundle, "--jobs", "0", "--out", str(out)]) == 2


@pytest.mark.req("ADC-EQP-005")
def test_the_vendor_template_passes_equipment_check(tmp_path: Path) -> None:
    template = REPO / "equipment/TEMPLATE.vendor.yaml"
    source = REPO / "equipment/TEMPLATE.source.yaml"
    assert equipment_cli(["check", str(template), "--source", str(source)]) == 0


@pytest.mark.req("ADC-EQP-005")
def test_a_vendor_entry_not_under_cc_by_4_is_refused(tmp_path: Path) -> None:
    source = yaml.safe_load((REPO / "equipment/TEMPLATE.source.yaml").read_text("utf-8"))
    source["vendor-example"]["licence"] = "proprietary"
    other = tmp_path / "source.yaml"
    other.write_text(yaml.safe_dump(source), encoding="utf-8")
    template = REPO / "equipment/TEMPLATE.vendor.yaml"
    assert equipment_cli(["check", str(template), "--source", str(other)]) == 1


@pytest.mark.req("ADC-EQP-005")
def test_an_entry_whose_module_does_not_read_a_value_is_refused(tmp_path: Path) -> None:
    data = yaml.safe_load((REPO / "equipment/TEMPLATE.vendor.yaml").read_text("utf-8"))
    data["params"]["chiller_kwh"] = data["params"].pop("chiller_kw")
    entry = tmp_path / "entry.yaml"
    entry.write_text(yaml.safe_dump(data), encoding="utf-8")
    source = REPO / "equipment/TEMPLATE.source.yaml"
    assert equipment_cli(["check", str(entry), "--source", str(source)]) == 1
