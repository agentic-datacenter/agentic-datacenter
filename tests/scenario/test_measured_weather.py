"""A scenario run on a measured weather series: determinism and provenance (ADR 0018).

The series is synthetic and written by the test; no real dataset is used.
"""

import json
from pathlib import Path

import pytest

from agentic_datacenter.core.profile import Profile, load_profile
from agentic_datacenter.data import write_manifest
from agentic_datacenter.governance.bindings import static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import ScriptedAdversarial
from agentic_datacenter.scenarios.evidence import MEASURED_STATEMENT, STATEMENTS, build_bundle
from agentic_datacenter.scenarios.harness import RunResult, run_scenario
from agentic_datacenter.scenarios.scenario import load_scenario

REPO = Path(__file__).resolve().parents[2]
GENERIC = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
SCENARIO = load_scenario("AD-03")
ANCHOR = "2020-07-01T01:00:00Z"
SECONDS = 600


def dataset(directory: Path, temps: list[float]) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    rows = ["time_utc,dry_bulb"] + [f"2020-07-01T{h:02d}:00:00Z,{t}" for h, t in enumerate(temps)]
    (directory / "series.csv").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return write_manifest(
        directory / "series.csv", dataset_id="synthetic_site", title="test", source="test",
        version="1", licence="none; synthetic", redistribution="not_cleared",
        quality_status="synthetic", units={"dry_bulb": "degC"}, gap_tolerance_s=0,
    )  # fmt: skip


def measured_profile(manifest: Path) -> Profile:
    profile = GENERIC.with_param("cooling.weather", "source", "measured")
    profile = profile.with_param("cooling.weather", "manifest", str(manifest))
    return profile.with_param("cooling.weather", "anchor_utc", ANCHOR)


def run(profile: Profile) -> RunResult:
    gate = static_allowlist.create(CONTRACTS)
    return run_scenario(
        SCENARIO, profile, gate, gate.profile, ScriptedAdversarial(), 1, CONTRACTS, SECONDS
    )


@pytest.fixture(scope="module")
def warm(tmp_path_factory: pytest.TempPathFactory) -> Path:
    return dataset(tmp_path_factory.mktemp("warm"), [30.0, 32.0, 35.0, 33.0])


@pytest.mark.req("ADC-KRN-001")
def test_same_file_same_seed_gives_identical_state_hashes(warm: Path) -> None:
    first, second = run(measured_profile(warm)), run(measured_profile(warm))
    assert first.state_hashes == second.state_hashes


def test_a_different_series_gives_a_different_run(warm: Path, tmp_path: Path) -> None:
    other = dataset(tmp_path, [10.0, 12.0, 15.0, 13.0])
    assert (
        run(measured_profile(warm)).state_hashes[-1]
        != run(measured_profile(other)).state_hashes[-1]
    )


@pytest.mark.req("ADC-EVD-001")
def test_bundle_marks_the_weather_as_derived_from_a_measured_series(warm: Path) -> None:
    profile = measured_profile(warm)
    bundle = build_bundle(run(profile), profile, SCENARIO, CONTRACTS, commit="abc123")
    manifest = json.loads(bundle["manifest.json"])
    [entry] = manifest["measured_inputs"]
    assert entry["instance"] == "cooling.weather[SITE]"
    assert entry["derived_from_measured_series"] is True
    assert entry["measurement_of_simulated_plant"] is False
    assert entry["points"] == ["dry_bulb_c"]
    assert entry["anchor_utc"] == ANCHOR
    # Simulated t=0 is the start of the 600 s warm-up; the scenario starts after it.
    assert entry["window_utc"] == ["2020-07-01T01:00:00Z", "2020-07-01T01:20:00Z"]
    assert entry["scenario_start_utc"] == "2020-07-01T01:10:00Z"
    assert entry["bridged_gaps_in_window"] == []
    dataset_ = entry["dataset"]
    assert dataset_["manifest_sha256"] and dataset_["files"]["series.csv"]
    assert dataset_["licence"] == "none; synthetic" and dataset_["redistribution"] == "not_cleared"
    assert manifest["statements"] == [*STATEMENTS, MEASURED_STATEMENT]


def test_bundle_of_the_synthetic_default_is_unchanged() -> None:
    bundle = build_bundle(run(GENERIC), GENERIC, SCENARIO, CONTRACTS, commit="abc123")
    manifest = json.loads(bundle["manifest.json"])
    assert "measured_inputs" not in manifest and manifest["statements"] == STATEMENTS
