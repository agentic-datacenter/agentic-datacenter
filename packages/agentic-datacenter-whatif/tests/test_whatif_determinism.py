"""Same request, same answer; and every bundle verifies (ADC-WIF-005)."""

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.evidence import verify_bundle
from agentic_datacenter.whatif.evidence import verify_whatif, write_whatif
from agentic_datacenter.whatif.models import WhatIfSpec
from agentic_datacenter.whatif.runner import run_whatif


@pytest.mark.req("ADC-WIF-005")
def test_two_runs_of_one_request_give_identical_metrics_series_and_hashes(
    make_spec: Callable[..., WhatIfSpec],
    profile: Profile,
    contracts: ContractLibrary,
    stand_in_gates: dict[str, Any],
) -> None:
    spec = make_spec(20.5, duration_s=1800, branches=["baseline", "physical", "governed"])
    first = run_whatif(spec, profile, contracts, gates=stand_in_gates)
    second = run_whatif(spec, profile, contracts, gates=stand_in_gates)
    assert json.dumps(first.summary(), sort_keys=True) == json.dumps(
        second.summary(), sort_keys=True
    )
    for name in ("baseline", "physical", "governed"):
        a, b = first.branches[name], second.branches[name]
        assert a.run is not None and b.run is not None
        assert a.run.state_hashes == b.run.state_hashes and a.run.state_hashes
        assert a.series == b.series


@pytest.mark.req("ADC-WIF-005")
def test_the_evidence_verifies_branch_by_branch_and_as_a_whole(
    make_spec: Callable[..., WhatIfSpec],
    profile: Profile,
    contracts: ContractLibrary,
    tmp_path: Path,
) -> None:
    spec = make_spec(20.5, duration_s=1800)
    result = run_whatif(spec, profile, contracts, gates={})
    out = write_whatif(result, tmp_path / "wf", profile, contracts, commit="test")
    manifest = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["request"] == spec.model_dump(mode="json")
    assert manifest["request_hash"] == spec.hash()
    assert set(manifest["start_state_hashes"]) == {"baseline", "physical"}
    assert manifest["branches"]["physical"]["hypothetical"] is True
    for name in ("baseline", "physical"):
        bundle = out / manifest["branches"][name]["bundle"]
        assert verify_bundle(bundle) == []
        branch_manifest = json.loads((bundle / "manifest.json").read_text(encoding="utf-8"))
        assert {"series.json", "branch.json"} <= set(branch_manifest["files"])
    assert verify_bundle(out) == [] and verify_whatif(out) == []
    (out / manifest["branches"]["physical"]["bundle"] / "series.json").write_text("[]\n")
    problems = verify_whatif(out)
    assert any("series.json" in p for p in problems)


def test_writing_the_same_result_twice_gives_the_same_bytes(
    make_spec: Callable[..., WhatIfSpec],
    profile: Profile,
    contracts: ContractLibrary,
    tmp_path: Path,
) -> None:
    spec = make_spec(19.5, duration_s=900)
    result = run_whatif(spec, profile, contracts, gates={})
    a = write_whatif(result, tmp_path / "a", profile, contracts, commit="test")
    b = write_whatif(result, tmp_path / "b", profile, contracts, commit="test")
    files = sorted(p.relative_to(a) for p in a.rglob("*") if p.is_file())
    assert files == sorted(p.relative_to(b) for p in b.rglob("*") if p.is_file())
    for name in files:
        assert (a / name).read_bytes() == (b / name).read_bytes(), name
