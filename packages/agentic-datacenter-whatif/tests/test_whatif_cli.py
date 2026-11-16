"""``agentic-datacenter whatif run``, ``policy`` and ``verify``."""

import json
from pathlib import Path

from agentic_datacenter.core.cli import main

REPO = Path(__file__).resolve().parents[3]


def test_run_writes_the_summary_series_and_evidence_and_verify_passes(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "scenario": "WF-01", "duration_s": 900, "branches": ["baseline", "physical"],
        "change": {"contract_id": "chw.set_supply_setpoint.v1", "argument": "setpoint_c",
                   "target": 20.5},
        "policy": {"enabled": False},
    }), encoding="utf-8")  # fmt: skip
    out = tmp_path / "out"
    status = main([
        "whatif", "run", "--spec", str(spec), "--out", str(out),
        "--profile", str(REPO / "profiles/generic_dc.yaml"),
        "--contracts", str(REPO / "contracts"),
    ])  # fmt: skip
    assert status == 0
    for name in ("summary.json", "series.json", "preflight.json", "policy.json", "manifest.json"):
        assert (out / name).is_file(), name
    summary = json.loads((out / "summary.json").read_text(encoding="utf-8"))
    assert summary["branches"]["physical"]["hypothetical"] is True
    assert main(["whatif", "verify", str(out)]) == 0
    (out / "summary.json").write_text("{}", encoding="utf-8")
    assert main(["whatif", "verify", str(out)]) == 1


def test_policy_writes_a_bundle_of_its_own(tmp_path: Path) -> None:
    spec = tmp_path / "spec.json"
    spec.write_text(json.dumps({
        "scenario": "WF-01",
        "change": {"contract_id": "chw.set_supply_setpoint.v1", "argument": "setpoint_c",
                   "target": 20.5},
    }), encoding="utf-8")  # fmt: skip
    out = tmp_path / "policy"
    status = main([
        "whatif", "policy", "--spec", str(spec), "--out", str(out),
        "--profile", str(REPO / "profiles/generic_dc.yaml"),
        "--contracts", str(REPO / "contracts"),
    ])  # fmt: skip
    assert status == 0
    policy = json.loads((out / "policy.json").read_text(encoding="utf-8"))
    assert policy["grants"] == "nothing"
    assert main(["whatif", "verify", str(out)]) == 0


def test_a_bad_request_file_is_refused_with_a_message(tmp_path: Path, capsys) -> None:  # type: ignore[no-untyped-def]
    spec = tmp_path / "spec.json"
    spec.write_text('{"scenario": "WF-01"}', encoding="utf-8")
    assert main(["whatif", "run", "--spec", str(spec), "--out", str(tmp_path / "o")]) == 2
    assert "change" in capsys.readouterr().err
