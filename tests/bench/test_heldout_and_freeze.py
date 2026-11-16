"""Track D (held-out variants), freezing a benchmark version, and the verifiable demo."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_datacenter.core.cli import main
from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings import static_allowlist
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.bench import benchmark_version, run_benchmark
from agentic_datacenter.scenarios.evidence import verify_bundle
from agentic_datacenter.scenarios.heldout import commitment, variants
from agentic_datacenter.scenarios.scenario import library_ids, load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
GATES = {
    "null_gate": lambda contracts: NullGate(),
    "static_allowlist": static_allowlist.create,
}


def test_variants_follow_the_secret_and_nothing_else() -> None:
    template = load_scenario("OP-03")
    first, again = variants(template, "secret-a", 4), variants(template, "secret-a", 4)
    other = variants(template, "secret-b", 4)
    assert [v.hash() for v in first] == [v.hash() for v in again]
    assert {v.hash() for v in first}.isdisjoint({v.hash() for v in other})
    assert len({v.hash() for v in first} | {template.hash()}) == 5


def test_a_variant_is_the_template_with_other_numbers() -> None:
    template = load_scenario("OP-03")
    for variant in variants(template, "secret-a", 6):
        assert variant.track == "D" and variant.id == template.id
        assert variant.pass_criteria == template.pass_criteria
        assert variant.duration_s == template.duration_s
        assert len(variant.timeline) == len(template.timeline)
        for was, now in zip(template.timeline, variant.timeline, strict=True):
            assert (was.module, was.inject) == (now.module, now.inject)
            assert 0 <= now.at_s < variant.duration_s
            assert abs(now.at_s - was.at_s) <= 0.2 * template.duration_s
            for name, value in was.params.items():
                if isinstance(value, float):
                    assert 0.9 * value <= float(now.params[name]) <= 1.1 * value
                else:
                    assert now.params[name] == value, "identifiers are not perturbed"
        peak = variant.timeline[0].params["peak_c"]
        assert peak != 36.0


def test_the_commitment_binds_the_secret_without_showing_it() -> None:
    assert commitment("secret-a") == commitment("secret-a") != commitment("secret-b")
    assert len(commitment("secret-a")) == 64 and "secret-a" not in commitment("secret-a")


def test_a_card_with_held_out_variants_says_so_and_keeps_them_apart() -> None:
    card = run_benchmark(
        PROFILE, CONTRACTS, GATES, ["scripted_adversarial"], ["OP-03"], [1], 900,
        counterfactual=False, allow_unfrozen=True, heldout_secret="secret-a", heldout_variants=2,
    )  # fmt: skip
    assert card["heldout"] == {"commitment": commitment("secret-a"), "variants_per_template": 2}
    tracks = {run["run_id"]: run["track"] for run in card["runs"]}
    assert sorted(tracks.values()).count("D") == 4 and len(tracks) == 6
    assert all(".D" in run_id for run_id, track in tracks.items() if track == "D")
    for row in card["results"]:
        assert row["heldout"]["runs"] == 2 and "safety" in row["heldout"]
    assert "secret-a" not in json.dumps(card)


@pytest.mark.req("ADC-BEN-001")
def test_freeze_writes_the_version_and_a_frozen_run_needs_no_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(REPO)
    frozen = tmp_path / "VERSION.json"
    assert main(["bench", "freeze", "--out", str(frozen)]) == 0
    written = json.loads(frozen.read_text(encoding="utf-8"))
    assert written["version"] == benchmark_version(PROFILE, CONTRACTS, library_ids())
    assert written["scenarios"] == library_ids()
    assert main(["bench", "freeze", "--out", str(frozen)]) == 1, "a version is frozen once"
    assert "already" in capsys.readouterr().err
    arguments = [
        "bench", "run", "--gate", "null_gate", "--agent", "scripted_benign", "--seconds", "600",
        "--no-counterfactual", "--frozen", str(frozen), "--out", str(tmp_path / "card"),
    ]  # fmt: skip
    assert main([*arguments, "--scenario", "OP-03"]) == 1, "a subset is not the frozen version"
    assert "scenario_library" in capsys.readouterr().err


def test_the_demo_leaves_an_evidence_bundle_for_each_side(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(REPO)
    assert (
        main(["demo", "--gate", "static_allowlist", "--seconds", "900", "--out", str(tmp_path)])
        == 0
    )
    bundles = sorted(p for p in (tmp_path / "evidence").iterdir() if p.is_dir())
    assert [b.name for b in bundles] == [
        "AD-05.null_gate", "AD-05.static_allowlist", "OP-03.null_gate",
        "OP-03.static_allowlist", "OP-10.null_gate", "OP-10.static_allowlist",
    ]  # fmt: skip
    assert all(verify_bundle(bundle) == [] for bundle in bundles)
    listed = json.loads((tmp_path / "demo.json").read_text(encoding="utf-8"))
    side = listed["scenarios"][0]["sides"][1]
    manifest = json.loads((bundles[3] / "manifest.json").read_text(encoding="utf-8"))
    assert side["evidence"] == "evidence/OP-03.static_allowlist"
    assert manifest["final_state_hash"] == side["final_state_hash"]
    (bundles[3] / "decisions.jsonl").write_text("{}\n", encoding="utf-8")
    assert verify_bundle(bundles[3]) != []
