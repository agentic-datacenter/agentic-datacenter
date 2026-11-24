"""What fits a facility of its owner's, and what a card from one says (ADR 0033, PR 2)."""

import json
from pathlib import Path
from typing import Any

import pytest
import yaml

from agentic_datacenter.core.facility import load_facility
from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.bench import load_gates, run_benchmark
from agentic_datacenter.scenarios.cli import facility as facility_cli
from agentic_datacenter.scenarios.facility_fit import fit_facility
from agentic_datacenter.scenarios.release_gate import check_card
from agentic_datacenter.scenarios.scenario import library_ids

REPO = Path(__file__).resolve().parents[2]
GENERIC = REPO / "profiles/generic_dc.yaml"
LIBRARY = ContractLibrary.load(REPO / "contracts")


def small_facility(tmp_path: Path) -> Path:
    """The generic facility with four PODs and no thermal storage tank."""
    data: dict[str, Any] = yaml.safe_load(GENERIC.read_text(encoding="utf-8"))
    data["name"] = "four_pods"
    pods = ["01", "02", "03", "04"]
    data["key_sets"]["pods"] = pods
    data["tables"]["pod_feeds"] = [r for r in data["tables"]["pod_feeds"] if r["pods"] in pods]
    data["modules"] = [m for m in data["modules"] if m["id"] != "cooling.tes"]
    connections = []
    for c in data["connections"]:
        if "cooling.tes" in c["consumer"]:
            continue
        if "cooling.tes" in c["provider"]:
            c = {**c, "provider": "cooling.chw_plant[CHW].chws"}
        connections.append(c)
    data["connections"] = connections
    path = tmp_path / "four_pods.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


@pytest.mark.req("ADC-FAC-007")
@pytest.mark.req("ADC-FAC-008")
def test_on_the_generic_facility_every_contract_loads_and_every_scenario_runs() -> None:
    fit = fit_facility(load_profile(GENERIC), LIBRARY, library_ids())
    assert fit.not_loaded == {} and fit.not_run == {}
    assert fit.contracts.ids() == LIBRARY.ids()
    assert fit.runnable == library_ids()


@pytest.mark.req("ADC-FAC-007")
def test_a_contract_that_does_not_fit_is_listed_with_what_it_lacks(tmp_path: Path) -> None:
    fit = fit_facility(load_profile(small_facility(tmp_path)), LIBRARY, library_ids())
    assert "chw.set_supply_setpoint.v1" in fit.not_loaded
    assert "TES-1" in fit.not_loaded["chw.set_supply_setpoint.v1"]
    assert "pod.set_supply_air_setpoint.v1" in fit.contracts.ids()
    assert set(fit.contracts.ids()) | set(fit.not_loaded) == set(LIBRARY.ids())


@pytest.mark.req("ADC-FAC-008")
def test_a_scenario_that_names_what_the_facility_lacks_is_not_run(tmp_path: Path) -> None:
    fit = fit_facility(load_profile(small_facility(tmp_path)), LIBRARY, library_ids())
    assert fit.not_run["OP-06"] == "needs cooling.pod[07]"  # a leak in POD 07
    assert "cooling.pod[11]" in fit.not_run["AD-03"] or "07" in fit.not_run["AD-03"]
    assert "OP-05" in fit.runnable  # an AHU failure in POD 03
    assert sorted(fit.runnable + list(fit.not_run)) == sorted(library_ids())


def _card(profile: Any, contracts: ContractLibrary, ids: list[str], **extra: Any) -> Any:
    gates = load_gates()
    return run_benchmark(
        profile, contracts, {"null_gate": gates["null_gate"]}, ["scripted_benign"], ids, [1],
        duration_s=60, counterfactual=False, allow_unfrozen=True, **extra,
    )  # fmt: skip


@pytest.mark.req("ADC-FAC-009")
def test_a_card_from_ones_own_facility_names_it_and_is_never_a_result(tmp_path: Path) -> None:
    facility = load_facility(small_facility(tmp_path))
    fit = fit_facility(facility.profile, LIBRARY, ["OP-05", "OP-06"])
    card = _card(
        facility.profile,
        fit.contracts,
        fit.runnable,
        facility={**facility.summary(), **fit.block()},
    )
    assert card["label"] == "result on a facility of its owner, not a benchmark result"
    assert card["benchmark_version"]["frozen"] is False
    block = card["facility"]
    assert block["name"] == "four_pods"
    assert block["profile_hash"] == facility.profile.hash()
    assert block["scenarios_not_run"] == {"OP-06": "needs cooling.pod[07]"}
    assert "chw.set_supply_setpoint.v1" in block["contracts_not_loaded"]
    assert card["scenarios"] == ["OP-05"]
    report = check_card(card, "null_gate", publication=True)
    assert any("facility of its owner" in v for v in report.violations)


@pytest.mark.req("ADC-FAC-009")
def test_a_card_without_a_facility_has_no_facility_block() -> None:
    card = _card(load_profile(GENERIC), LIBRARY, ["OP-05"])
    assert "facility" not in card
    assert card["label"] == "development run, not a benchmark result"


@pytest.mark.req("ADC-FAC-006")
def test_facility_check_writes_what_applies_and_how_the_plant_ran(tmp_path: Path) -> None:
    out = tmp_path / "report"
    status = facility_cli(["check", str(small_facility(tmp_path)), "--out", str(out)])
    assert status == 0
    report = json.loads((out / "facility_report.json").read_text(encoding="utf-8"))
    assert report["facility"]["name"] == "four_pods"
    assert "chw.set_supply_setpoint.v1" in report["fit"]["contracts_not_loaded"]
    assert report["fit"]["scenarios_not_run"]["OP-06"] == "needs cooling.pod[07]"
    assert report["run"]["seconds"] == 300
    assert report["run"]["it_served_kw"] == pytest.approx(600.0, rel=0.05)
    assert report["run"]["facility_kw"] > report["run"]["it_served_kw"]
    text = (out / "facility_report.md").read_text(encoding="utf-8")
    assert "Not run" in text and "OP-06" in text


@pytest.mark.req("ADC-FAC-006")
def test_facility_compile_writes_the_profile_a_bundle_lowers_to(tmp_path: Path) -> None:
    out = tmp_path / "lowered.yaml"
    assert facility_cli(["compile", str(GENERIC), "--out", str(out)]) == 0
    assert load_profile(out).hash() == load_profile(GENERIC).hash()


@pytest.mark.req("ADC-FAC-006")
def test_the_example_bundle_has_three_kinds_of_pod_and_runs(tmp_path: Path) -> None:
    example = load_facility(REPO / "examples/byodc")
    loads = {s.instance: s.params["design_kw"] for s in example.profile.instances()
             if s.module_id == "electrical.it_load"}  # fmt: skip
    assert sorted(set(loads.values())) == [80.0, 150.0, 300.0]
    assert facility_cli(["check", str(REPO / "examples/byodc"), "--out", str(tmp_path)]) == 0
    report = json.loads((tmp_path / "facility_report.json").read_text(encoding="utf-8"))
    assert report["run"]["it_served_kw"] == pytest.approx(sum(loads.values()), rel=0.01)
    assert report["fit"]["contracts_not_loaded"] == {}
