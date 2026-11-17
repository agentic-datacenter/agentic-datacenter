"""Releases and result cards are attested where the workflow runs (ADR 0025)."""

from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[2]
WORKFLOWS = sorted((REPO / ".github/workflows").glob("*.yml"))
ATTESTING = {("release", "build"), ("bench-runner", "bench")}
SIGNING = {"contents": "read", "id-token": "write", "attestations": "write"}
PUBLIC_ONLY = "${{ !github.event.repository.private }}"


def job(workflow: str, name: str) -> dict[str, Any]:
    data = yaml.safe_load((REPO / f".github/workflows/{workflow}.yml").read_text("utf-8"))
    return data["jobs"][name]  # type: ignore[no-any-return]


def attests(step: dict[str, Any]) -> bool:
    return str(step.get("uses", "")).startswith("actions/attest@")


def test_only_the_two_attesting_jobs_may_ask_for_a_signing_identity() -> None:
    for path in WORKFLOWS:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        for name, body in data["jobs"].items():
            wanted = SIGNING if (path.stem, name) in ATTESTING else None
            assert body.get("permissions") == wanted, (path.name, name)
            assert any(attests(s) for s in body["steps"]) == (wanted is not None), path.name


def test_an_attestation_is_made_on_a_public_repository_only() -> None:
    """A private repository of a personal account cannot store one; the step would fail."""
    for workflow, name in ATTESTING:
        steps = [s for s in job(workflow, name)["steps"] if attests(s)]
        assert steps and all(s.get("if") == PUBLIC_ONLY for s in steps), workflow


def test_a_release_attests_every_distribution_and_its_bill_of_materials() -> None:
    steps = job("release", "build")["steps"]
    runs = [s.get("run", "") for s in steps]
    sbom = [i for i, r in enumerate(runs) if "uv export" in r and "cyclonedx1.5" in r]
    assert sbom and "--frozen" in runs[sbom[0]] and "dist/sbom.cdx.json" in runs[sbom[0]]
    checked = [i for i, r in enumerate(runs) if "tools/check_dist_licences.py" in r][0]
    provenance, materials = [i for i, s in enumerate(steps) if attests(s)]
    upload = [i for i, s in enumerate(steps) if "upload-artifact" in str(s.get("uses", ""))][0]
    assert checked < sbom[0] < provenance < materials < upload
    for index in (provenance, materials):
        subject = steps[index]["with"]["subject-path"]
        assert "dist/*.whl" in subject and "dist/*.tar.gz" in subject
    assert "sbom-path" not in steps[provenance]["with"]
    assert steps[materials]["with"]["sbom-path"] == "dist/sbom.cdx.json"


def test_the_benchmark_runner_records_what_it_made_and_attests_the_record() -> None:
    steps = job("bench-runner", "bench")["steps"]
    runs = [s.get("run", "") for s in steps]
    checked = [i for i, r in enumerate(runs) if "bench check" in r][0]
    recorded = [i for i, r in enumerate(runs) if 'bench record "$OUT"' in r][0]
    (attested,) = [i for i, s in enumerate(steps) if attests(s)]
    kept = [i for i, s in enumerate(steps) if "upload-artifact" in str(s.get("uses", ""))][0]
    assert checked < recorded < attested < kept
    assert steps[attested]["with"]["subject-path"] == "${{ env.OUT }}/provenance.json"
