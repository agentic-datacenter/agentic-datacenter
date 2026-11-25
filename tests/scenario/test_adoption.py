"""Starting points for operators and makers (the adoption phase)."""

import json
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
def test_facility_report_gives_an_operator_one_page(tmp_path: Path) -> None:
    out = tmp_path / "report"
    status = facility_cli(
        ["report", str(REPO / "examples/byodc"), "--gate", "static_allowlist", "--out", str(out)]
    )
    assert status == 0
    page = (out / "operator_report.md").read_text(encoding="utf-8")
    assert "result on a facility of its owner, not a benchmark result" in page
    assert "| `static_allowlist` | scripted_adversarial |" in page
    card = json.loads((out / "result_card.json").read_text(encoding="utf-8"))
    assert card["facility"]["name"] == "example_mixed_pods"
    assert (out / "facility_report.md").is_file() and (out / "report.html").is_file()


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
