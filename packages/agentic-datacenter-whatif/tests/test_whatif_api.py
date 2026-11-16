"""The job API: submit, follow, read the parts of the result (ADR 0019)."""

from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.whatif.api import JobStore, create_router

REQUEST: dict[str, Any] = {
    "scenario": "WF-01",
    "duration_s": 900,
    "branches": ["baseline", "physical"],
    "change": {
        "contract_id": "chw.set_supply_setpoint.v1",
        "argument": "setpoint_c",
        "target": 20.5,
    },
    "policy": {"enabled": False},
}


@pytest.fixture
def client(profile: Profile, contracts: ContractLibrary, tmp_path: Path) -> Any:
    store = JobStore(tmp_path / "jobs", profile, contracts, gates={}, commit="test")
    app = FastAPI()
    app.include_router(create_router(store))
    with TestClient(app) as http:
        yield http, store
    store.close()


@pytest.mark.req("ADC-WIF-005")
def test_a_job_runs_in_the_background_and_its_parts_can_be_read(client: Any) -> None:
    http, store = client
    answer = http.post("/api/v1/whatif/runs", json=REQUEST)
    assert answer.status_code == 202
    job = answer.json()["id"]
    assert job.startswith("wf-") and answer.json()["status"] in ("queued", "running", "done")
    store.join()
    status = http.get(f"/api/v1/whatif/runs/{job}").json()
    assert status["status"] == "done", status
    assert status["summary"]["branches"]["physical"]["hypothetical"] is True
    series = http.get(f"/api/v1/whatif/runs/{job}/series").json()
    assert set(series) == {"baseline", "physical"} and series["baseline"][0]["t_s"] == 900
    policy = http.get(f"/api/v1/whatif/runs/{job}/policy").json()
    assert policy["available"] is False and policy["grants"] == "nothing"
    evidence = http.get(f"/api/v1/whatif/runs/{job}/evidence").json()
    assert evidence["problems"] == [] and evidence["manifest"]["request_hash"]


def test_the_same_request_gives_the_same_result_under_a_new_id(client: Any) -> None:
    http, store = client
    first = http.post("/api/v1/whatif/runs", json=REQUEST).json()["id"]
    second = http.post("/api/v1/whatif/runs", json=REQUEST).json()["id"]
    assert first != second and first[:15] == second[:15]
    store.join()
    a = http.get(f"/api/v1/whatif/runs/{first}").json()["summary"]
    b = http.get(f"/api/v1/whatif/runs/{second}").json()["summary"]
    assert a == b


def test_an_invalid_request_is_refused_before_anything_runs(client: Any) -> None:
    http, _ = client
    answer = http.post("/api/v1/whatif/runs", json={**REQUEST, "branches": ["physical"]})
    assert answer.status_code == 422 and "baseline" in answer.text


def test_an_unknown_job_is_not_found(client: Any) -> None:
    http, _ = client
    assert http.get("/api/v1/whatif/runs/wf-000000000000-0001").status_code == 404
    assert http.get("/api/v1/whatif/runs/nope/series").status_code == 404


def test_a_part_of_an_unfinished_job_is_a_conflict(client: Any) -> None:
    http, store = client
    store.pause()
    job = http.post("/api/v1/whatif/runs", json=REQUEST).json()["id"]
    assert http.get(f"/api/v1/whatif/runs/{job}").json()["status"] == "queued"
    assert http.get(f"/api/v1/whatif/runs/{job}/series").status_code == 409
    store.resume()
    store.join()
    assert http.get(f"/api/v1/whatif/runs/{job}/series").status_code == 200


def test_the_contracts_that_can_be_studied_are_listed_with_their_limits(client: Any) -> None:
    http, _ = client
    listed = http.get("/api/v1/whatif/contracts").json()
    chw = next(c for c in listed if c["id"] == "chw.set_supply_setpoint.v1")
    assert chw["argument"] == "setpoint_c"
    assert chw["bounds"] == {"min": 16.0, "max": 21.0, "max_step": 0.5, "unit": "degC"}
    assert chw["limits"]["rate"] == {"max_per_hour": 2}
    assert chw["limits"]["cumulative"] == {"window_h": 24.0, "max_total_delta": 2.0}
    assert all(c["id"] != "chw.rotate_lead_chiller.v1" for c in listed)
