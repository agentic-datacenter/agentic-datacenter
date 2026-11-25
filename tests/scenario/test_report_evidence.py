"""Report comparisons and provenance from recorded data."""

import json
from pathlib import Path

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.cli import load_gates
from agentic_datacenter.scenarios.demo import build_demo
from agentic_datacenter.scenarios.executive import render_executive, render_executive_markdown

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.req("ADC-UX-011")
def test_recording_compares_every_selected_gate_and_records_the_model() -> None:
    profile = load_profile(ROOT / "profiles/generic_dc.yaml")
    library = ContractLibrary.load(ROOT / "contracts")
    gates = load_gates()
    gates["another_control"] = gates["static_allowlist"]
    recording = build_demo(
        profile,
        library,
        gates,
        "static_allowlist",
        seconds=60,
        only=("OP-03",),
        additional_gates=("another_control",),
    )
    scenario = recording["scenarios"][0]
    assert [side["gate"] for side in scenario["sides"]] == [
        "null_gate",
        "static_allowlist",
        "another_control",
    ]
    assert recording["facility"]["profile_hash"] == profile.hash()
    assert "cooling.weather[SITE]" in recording["facility"]["instances"]
    weather = scenario["sides"][0]["telemetry"]["cooling.weather[SITE].dry_bulb_c"]
    assert weather["unit"] == "degC"
    assert len(weather["values"]) == len(scenario["sides"][0]["series"]["t_s"])
    assert scenario["events"]
    for page in (render_executive(recording), render_executive_markdown(recording)):
        assert "another_control" in page
        assert "Outdoor dry-bulb temperature" in page
        assert "Run inputs and evidence" in page


@pytest.mark.req("ADC-UX-011")
def test_historical_report_keeps_unknown_weather_and_inputs_explicit() -> None:
    recording = json.loads((ROOT / "docs/demo/demo.json").read_text(encoding="utf-8"))
    report = render_executive_markdown(recording)
    assert "Outdoor conditions were not recorded" in report
    assert "Scenario event timeline was not recorded" in report
    assert "Agent proposals and outcomes" in report
    assert "delta" in report.lower()
    assert "evidence/OP-03.remora_governed" not in report
