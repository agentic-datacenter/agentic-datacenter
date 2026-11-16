"""Contracts compile to the signed artifacts REMORA's governed path loads (ADC-GOV-006)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

pytest.importorskip("remora")

from agentic_datacenter.governance.contracts import ContractLibrary, parse_contract
from agentic_datacenter_remora.compile import (
    SCALE,
    CompileError,
    compile_contracts,
    limits_policy,
    restore_ids,
    signing_seeds,
    tool_metadata,
    unsigned_bundle,
)

REPO = Path(__file__).resolve().parents[3]
LIBRARY = ContractLibrary.load(REPO / "contracts")
CHW = "chw.set_supply_setpoint.v1"


def _contract(**changes: object) -> ContractLibrary:
    data: dict[str, object] = {
        "schema_version": 1, "id": "test.move.v1", "title": "Move", "risk_tier": "R1",
        "arguments": {"value": {"type": "number"}},
        "writes": [{"tag": "a[B].sp", "value": "value", "bounds": {"min": 1.0, "max": 9.0}}],
        "limits": {"cumulative": {"window_h": 1, "max_total_delta": 2.0}},
        "approval": "none",
    }  # fmt: skip
    data.update(changes)
    return ContractLibrary([parse_contract(data)])


@pytest.mark.req("ADC-GOV-006")
def test_compiling_twice_gives_the_same_bytes(tmp_path: Path) -> None:
    first = compile_contracts(LIBRARY, tmp_path / "a")
    second = compile_contracts(LIBRARY, tmp_path / "b")
    for name in ("toolspec-bundle.json", "limits.json", "tool_metadata.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes()
    assert first.manifest == second.manifest
    assert set(first.manifest["sha256"]) == {
        "toolspec-bundle.json", "limits.json", "tool_metadata.json",
    }  # fmt: skip


@pytest.mark.req("ADC-GOV-006")
def test_the_artifacts_are_signed_and_labelled_as_simulator_output(tmp_path: Path) -> None:
    compiled = compile_contracts(LIBRARY, tmp_path)
    bundle = json.loads((tmp_path / "toolspec-bundle.json").read_text(encoding="utf-8"))
    limits = json.loads((tmp_path / "limits.json").read_text(encoding="utf-8"))
    assert bundle["registry_signature"]["algorithm"].lower().startswith("ed25519")
    assert limits["schema"] == "remora-cumulative-limits-signed/v1"
    assert compiled.manifest["label"] == "simulator artifact, not for production"
    assert compiled.manifest["toolspec_pinned_digest"] and compiled.manifest["limits_public_key"]
    tools = {spec["tool_id"] for spec in bundle["tool_specs"]}
    contracts = {c for c in LIBRARY.ids() if c != "r3.hard_floor.v1"}
    assert tools == contracts | set(compiled.manifest["restore_tools"])
    assert compiled.manifest["restore_tools"] == {
        "chw.set_supply_setpoint.restore.v1": "chw.set_supply_setpoint.v1",
        "pod.set_supply_air_setpoint.restore.v1": "pod.set_supply_air_setpoint.v1",
        "pumps.set_dp_setpoint.restore.v1": "pumps.set_dp_setpoint.v1",
    }


def test_a_restore_tool_has_the_bounds_of_its_contract_and_no_limit() -> None:
    restore = restore_ids(LIBRARY)
    assert "chw.set_supply_setpoint.restore.v1" in restore
    specs = {s["tool_id"]: s for s in unsigned_bundle(LIBRARY)["tool_specs"]}
    for tool, contract in restore.items():
        assert specs[tool]["argument_schema"] == specs[contract]["argument_schema"]
        assert specs[tool]["risk_tier"] == specs[contract]["risk_tier"]
    policy = limits_policy(LIBRARY)
    limits = {lim["quantity"]: lim for lim in policy["limits"]}
    for tool in restore:
        assert [m["kind"] for m in policy["meters"][tool]] == ["count"]
        assert limits[f"calls:{tool}"]["max"] == 1_000_000, "declared, with no ceiling"


@pytest.mark.req("ADC-GOV-006")
def test_no_signing_seed_reaches_the_disk(tmp_path: Path) -> None:
    compile_contracts(LIBRARY, tmp_path)
    written = b"".join(p.read_bytes() for p in tmp_path.rglob("*") if p.is_file())
    for seed in signing_seeds(LIBRARY).values():
        assert seed.encode() not in written


@pytest.mark.req("ADC-GOV-006")
def test_bounds_become_the_argument_schema() -> None:
    specs = {s["tool_id"]: s for s in unsigned_bundle(LIBRARY)["tool_specs"]}
    schema = specs[CHW]["argument_schema"]
    assert schema["properties"]["setpoint_c"] == {
        "type": "number",
        "minimum": 16.0,
        "maximum": 21.0,
    }
    assert schema["properties"]["target"] == {"type": "string"}
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"setpoint_c", "target"}
    assert specs["chw.rotate_lead_chiller.v1"]["argument_schema"]["properties"]["lead"] == {
        "type": "string", "enum": ["1", "2", "3"],
    }  # fmt: skip
    # Every plant write is declared as REMORA's own pilot declares one.
    # R1 with a rollback is low; R1 without one, and R2, need a person: high.
    assert specs[CHW]["risk_tier"] == "low"
    assert specs["chw.precool.v1"]["risk_tier"] == "high"
    assert specs["genset.start_test_run.v1"]["risk_tier"] == "high"
    metadata = tool_metadata(LIBRARY)["tools"]
    for tool, spec in specs.items():
        assert metadata[tool]["risk_tier"] == spec["risk_tier"], "REMORA cross-checks these"
        assert metadata[tool]["action_type"] == spec["action_type"]
    assert {s["action_type"] for s in specs.values()} == {"write"}


@pytest.mark.req("ADC-GOV-006")
def test_limits_become_meters_in_whole_units() -> None:
    policy = limits_policy(LIBRARY)
    meters = {m["kind"]: m for m in policy["meters"][CHW]}
    assert meters["change"]["argument"] == "setpoint_c" and meters["change"]["scale"] == SCALE
    assert meters["change"]["resource_argument"] == meters["count"]["resource_argument"] == "target"
    limits = {limit["limit_id"]: limit for limit in policy["limits"]}
    moved = limits["cumulative:cooling.chw_plant[CHW].chws_sp_c"]
    assert moved["max"] == 2 * SCALE and moved["window_seconds"] == 24 * 3600
    assert moved["resource"] == "*" and moved["principal"] == "*"
    rate = limits[f"rate:{CHW}"]
    assert rate["max"] == 2 and rate["window_seconds"] == 3600
    assert "dual_control_above" not in rate
    assert limits["rate:chw.take_chiller_out_of_service.v1"]["dual_control_above"] == 0
    # A host cannot yet state through the SDK that a call did not run, so no
    # source is trusted for it: a refused write is held as unknown and resolved.
    assert "non_execution" not in policy


@pytest.mark.req("ADC-GOV-006")
def test_two_contracts_on_one_tag_share_its_cumulative_limit() -> None:
    policy = limits_policy(LIBRARY)
    quantities = {
        tool: next(m["quantity"] for m in meters if m["kind"] == "change")
        for tool, meters in policy["meters"].items()
        if any(m["kind"] == "change" for m in meters)
    }
    assert quantities[CHW] == quantities["chw.precool.v1"]
    ids = [limit["limit_id"] for limit in policy["limits"]]
    assert len(ids) == len(set(ids))


@pytest.mark.req("ADC-GOV-006")
@pytest.mark.parametrize(
    ("changes", "why"),
    [
        ({"writes": [{"tag": "a[B].sp", "value": "value"}]}, "no bounds"),
        ({"limits": {"cumulative": {"window_h": 1, "max_total_delta": 0.00001}}}, "whole"),
        ({"limits": {"cumulative": {"window_h": 0.0001, "max_total_delta": 2.0}}}, "whole"),
        ({"arguments": {"value": {"type": "number"}, "note": {"type": "text"}}}, "text"),
    ],
)
def test_a_contract_that_cannot_be_expressed_fails_the_build(
    tmp_path: Path, changes: dict[str, object], why: str
) -> None:
    with pytest.raises(CompileError, match=why):
        compile_contracts(_contract(**changes), tmp_path)
    assert not list(tmp_path.glob("*.json"))


@pytest.mark.req("ADC-GOV-006")
def test_the_manifest_says_what_stays_with_the_binding(tmp_path: Path) -> None:
    manifest = compile_contracts(LIBRARY, tmp_path).manifest
    kept = manifest["enforced_by_the_binding"][CHW]
    assert kept == ["max_step", "premises", "rollback", "writes beyond the first"]
    assert manifest["enforced_by_the_binding"]["genset.start_test_run.v1"] == ["premises"]


@pytest.mark.req("ADC-GOV-006")
def test_the_compile_command_writes_the_artifacts_and_fails_on_a_bad_library(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    from agentic_datacenter_remora.cli import contracts

    out = tmp_path / "out"
    assert contracts(["compile", "--contracts", str(REPO / "contracts"), "--out", str(out)]) == 0
    assert "not for production" in capsys.readouterr().out
    assert (out / "toolspec-bundle.json").is_file() and (out / "limits.json").is_file()
    empty = tmp_path / "empty"
    empty.mkdir()
    assert contracts(["compile", "--contracts", str(empty), "--out", str(tmp_path / "x")]) == 1
    assert "no contracts found" in capsys.readouterr().err
