"""ADC-EVD-001: each run produces an evidence bundle that can be checked by itself."""

import json
from pathlib import Path

import pytest

from agentic_datacenter.core.cli import main
from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings import static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import ScriptedAdversarial
from agentic_datacenter.scenarios.evidence import (
    STATEMENTS,
    build_bundle,
    verify_bundle,
    write_bundle,
)
from agentic_datacenter.scenarios.harness import RunResult, run_scenario
from agentic_datacenter.scenarios.scenario import load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
SCENARIO = load_scenario("AD-03")
FILES = {"manifest.json", "metrics.json", "state_hashes.jsonl", "decisions.jsonl",
         "change_log.jsonl", "escalations.jsonl"}  # fmt: skip


def run() -> RunResult:
    gate = static_allowlist.create(CONTRACTS)
    return run_scenario(
        SCENARIO, PROFILE, gate, gate.profile, ScriptedAdversarial(), 3, CONTRACTS, 900
    )


@pytest.fixture(scope="module")
def result() -> RunResult:
    return run()


@pytest.mark.req("ADC-EVD-001")
def test_bundle_holds_everything_the_requirement_lists(result: RunResult, tmp_path: Path) -> None:
    bundle = build_bundle(result, PROFILE, SCENARIO, CONTRACTS, commit="abc123", gate_commit=None)
    out = write_bundle(bundle, tmp_path / "bundle")
    assert {p.name for p in out.iterdir()} == FILES
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest["profile_hash"] == PROFILE.hash() and manifest["scenario"] == "AD-03"
    assert manifest["scenario_hash"] == SCENARIO.hash() and manifest["seed"] == 3
    assert manifest["code_commit"] == "abc123" and manifest["gate"] == "static_allowlist"
    assert manifest["operating_profile"] == "STATIC_ALLOWLIST" and manifest["duration_s"] == 900
    assert manifest["gate_commit"] is None and manifest["statements"] == STATEMENTS
    assert manifest["final_state_hash"] == result.state_hashes[-1][1]
    hashes = [json.loads(line) for line in (out / "state_hashes.jsonl").read_text().splitlines()]
    assert len(hashes) == 15 and hashes[0].keys() == {"time_ms", "state_hash"}
    decisions = (out / "decisions.jsonl").read_text().splitlines()
    assert len(decisions) == len(result.records) > 0
    assert json.loads(decisions[0])["decision_ref"] == result.records[0]["decision_ref"]
    assert len((out / "change_log.jsonl").read_text().splitlines()) == len(result.change_log)
    metrics = json.loads((out / "metrics.json").read_text())
    assert metrics["passed"] == result.passed and "critical_pod_minutes" in metrics["metrics"]
    assert set(manifest["files"]) == FILES - {"manifest.json"}


@pytest.mark.req("ADC-EVD-001")
def test_bundle_verifies_and_any_change_to_it_is_found(result: RunResult, tmp_path: Path) -> None:
    bundle = build_bundle(result, PROFILE, SCENARIO, CONTRACTS, commit="abc123", gate_commit=None)
    out = write_bundle(bundle, tmp_path / "bundle")
    assert verify_bundle(out) == []
    decisions = out / "decisions.jsonl"
    decisions.write_text(decisions.read_text().replace('"verdict": "', '"verdict": "NOT-', 1))
    assert verify_bundle(out) == ["decisions.jsonl does not match the hash in the manifest"]
    (out / "metrics.json").unlink()
    assert "metrics.json is missing" in verify_bundle(out)


@pytest.mark.req("ADC-EVD-001")
def test_the_same_run_gives_the_same_bundle(result: RunResult, tmp_path: Path) -> None:
    first = write_bundle(
        build_bundle(result, PROFILE, SCENARIO, CONTRACTS, commit="abc123", gate_commit=None),
        tmp_path / "a",
    )
    second = write_bundle(
        build_bundle(run(), PROFILE, SCENARIO, CONTRACTS, commit="abc123", gate_commit=None),
        tmp_path / "b",
    )
    for name in FILES:
        assert (first / name).read_bytes() == (second / name).read_bytes(), name


def test_scenario_command_writes_and_checks_a_bundle(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    monkeypatch.chdir(REPO)
    out = tmp_path / "run"
    status = main(
        ["scenario", "run", "AD-03", "--gate", "static_allowlist", "--agent",
         "scripted_adversarial", "--seconds", "600", "--out", str(out)]
    )  # fmt: skip
    assert status in (0, 1), "0 when the scenario passed, 1 when it did not"
    assert "AD-03" in capsys.readouterr().out and (out / "manifest.json").is_file()
    assert len(json.loads((out / "manifest.json").read_text())["code_commit"]) >= 7
    assert main(["scenario", "verify", str(out)]) == 0
    (out / "metrics.json").write_text("{}")
    assert main(["scenario", "verify", str(out)]) == 1
    assert main(["scenario", "run", "AD-03", "--gate", "nope", "--out", str(out)]) == 2
