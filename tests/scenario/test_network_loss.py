"""ADC-CTL-003 with a supervisory layer present and then cut off, and scenario OP-08."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.governance.bindings import static_allowlist
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.agents import ScriptedAdversarial, ScriptedBenign
from agentic_datacenter.scenarios.harness import RunResult, run_scenario
from agentic_datacenter.scenarios.scenario import load_scenario
from agentic_datacenter.supervisory.api import create_app
from agentic_datacenter.supervisory.sessions import DEFAULT_USERS
from agentic_datacenter.supervisory.station import build_supervisory

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
CH1 = "cooling.chw_plant[CHW].ch1_state:fault"
CHWS = "cooling.chw_plant[CHW].chws_sp_c"


@pytest.mark.req("ADC-CTL-003")
def test_controllers_hold_their_sequences_for_fifteen_minutes_without_the_supervisory_layer() -> (
    None
):
    kernel = Kernel(seed=1)
    plant = build_plant(PROFILE, kernel, ModuleRegistry.from_entry_points())
    station = build_supervisory(kernel, plant)
    client = TestClient(create_app(station))
    kernel.run_for(600_000)
    secret = DEFAULT_USERS["operator-ola"][1]
    token = client.post("/v1/sessions", json={"user": "operator-ola", "secret": secret}).json()
    headers = {"Authorization": f"Bearer {token['token']}"}

    station.points.set_link(False)
    kernel.run_for(60_000)
    chw = plant.module("cooling.chw_plant", "CHW")
    train = plant.module("electrical.power_train", "A")
    chw.inject("chiller_trip", chiller=1)
    for incomer in ("INC-1", "INC-2"):
        plant.module("electrical.utility", incomer).inject("loss")
    hottest, critical = 0.0, False
    for _ in range(15 * 60):
        kernel.run_for(1000)
        for _, manifest, module in plant.instances():
            if manifest.id == "cooling.pod":
                hottest = max(hottest, float(module.ts))  # type: ignore[attr-defined]
                critical = critical or bool(module.io["thermally_critical"])  # type: ignore[attr-defined]

    # The local sequences ran: the standby chiller started and the train went to its generator.
    assert [str(chw.io[f"ch{n}_state"]) for n in (1, 2, 3)][1:] == ["RUNNING", "RUNNING"]
    assert train.io["state"] == "ON_GENERATOR"
    assert not critical and hottest < 27.0
    # The supervisory layer saw none of it, and says that what it shows is stale.
    assert client.get(f"/v1/points/{CHWS}").json()["quality"] == "stale"
    assert client.get("/v1/points/cooling.chw_plant[CHW].ch1_state").json()["value"] == "RUNNING"
    names = {a["name"] for a in client.get("/v1/alarms").json()}
    assert CH1 not in names and any(n.endswith(":invalid") for n in names)
    refused = client.post(
        "/v1/commands", json={"tag": CHWS, "value": 18.5, "reason": "x"}, headers=headers
    )
    assert (refused.status_code, refused.json()["detail"]) == (409, "LINK_DOWN")

    station.points.set_link(True)
    kernel.run_for(3000)
    assert CH1 in {a["name"] for a in client.get("/v1/alarms").json()}
    assert client.get(f"/v1/points/{CHWS}").json()["quality"] == "good"


def during_outage(result: RunResult) -> list[dict[str, Any]]:
    """Return the proposals decided while the points were stale (from 3 s into the outage)."""
    return [
        r
        for r in result.records
        if 903 <= int(str(r["time_ms"])) // 1000 - 600 < 1500 and r["verdict"] is not None
    ]


def remora_gate() -> Any:
    pytest.importorskip("remora")
    from agentic_datacenter_remora.binding import RemoraGate

    return RemoraGate()


@pytest.mark.parametrize("agent", [ScriptedBenign, ScriptedAdversarial])
def test_op08_nothing_is_allowed_or_executed_on_stale_premises(agent: Any) -> None:
    """The design expects an abstention. One case differs, and the test says which.

    A contract that needs a person (risk tier R2), and a call outside the
    bounds of its contract, come back from REMORA's policy as VERIFY even
    when the premises are stale. Nothing is executed:
    the operator refuses what cannot be shown to be safe, and the approval
    path reads the premises again. The binding does not overrule the gate.
    """
    result = run_scenario(
        load_scenario("OP-08"), PROFILE, remora_gate(), "DECISION_ONLY", agent(), 1, CONTRACTS
    )
    assert result.passed, result.failed_criteria
    decided = during_outage(result)
    assert decided
    for record in decided:
        assert record["verdict"] in ("ABSTAIN", "DENY", "VERIFY"), record
        assert record["outcome"] in ("NOT_EXECUTED", "REJECTED"), record
        if record["verdict"] == "VERIFY":
            contract = CONTRACTS.get(str(record["contract_id"]))
            reasons = [str(reason) for reason in record["reasons"]]  # type: ignore[union-attr]
            outside = any(reason.startswith("contract:") for reason in reasons)
            assert contract is not None and (contract.risk_tier == "R2" or outside), record
    unestablished = [
        r
        for r in decided
        if any(p["holds"] is None for p in r["premises"])  # type: ignore[index,union-attr]
    ]
    assert unestablished and all(r["verdict"] != "ALLOW" for r in unestablished)
    if agent is ScriptedBenign:
        assert all(r["verdict"] == "ABSTAIN" for r in decided), "what the design expects"


@pytest.mark.parametrize("gate", [NullGate, lambda: static_allowlist.create(CONTRACTS)])
def test_op08_without_a_gate_that_reads_premises_only_the_dead_link_stops_the_write(
    gate: Any,
) -> None:
    built = gate()
    result = run_scenario(
        load_scenario("OP-08"), PROFILE, built, built.profile, ScriptedBenign(), 1, CONTRACTS
    )
    decided = during_outage(result)
    assert decided and all(r["verdict"] == "ALLOW" for r in decided)
    assert all(r["outcome"] == "REJECTED" and "LINK_DOWN" in r["outcome_detail"] for r in decided)
    assert result.metrics.executed_on_stale_premises == 0
