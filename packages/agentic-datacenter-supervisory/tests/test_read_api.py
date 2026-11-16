"""The operator API (SDD 8.3): reads without login, writes only through the command service."""

from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.supervisory.api import create_app
from agentic_datacenter.supervisory.sessions import DEFAULT_USERS
from agentic_datacenter.supervisory.station import Supervisory, build_supervisory

REPO = Path(__file__).resolve().parents[3]
CHWS = "cooling.chw_plant[CHW].chws_sp_c"
POD = "cooling.pod[01].supply_air_c"
BREAKER = "electrical.power_train[A].gen_brk_close_cmd"
CH1 = "cooling.chw_plant[CHW].ch1_state:fault"


def station() -> tuple[Kernel, Any, Supervisory, TestClient]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    supervisory = build_supervisory(kernel, plant)
    kernel.run_for(5000)
    return kernel, plant, supervisory, TestClient(create_app(supervisory))


def login(client: TestClient, user: str = "operator-ola") -> dict[str, str]:
    answer = client.post("/v1/sessions", json={"user": user, "secret": DEFAULT_USERS[user][1]})
    assert answer.status_code == 200
    return {"Authorization": f"Bearer {answer.json()['token']}"}


def test_points_are_read_without_login() -> None:
    _, _, _, client = station()
    one = client.get(f"/v1/points/{CHWS}").json()
    assert (one["value"], one["quality"], one["unit"], one["tier"]) == (18.0, "good", "degC", "T3")
    pod = client.get("/v1/points", params={"prefix": "cooling.pod[01]."}).json()
    assert len(pod) > 10 and all(p["tag"].startswith("cooling.pod[01].") for p in pod)
    assert len(client.get("/v1/points").json()) >= 700
    assert client.get("/v1/points/no.such[X].point").status_code == 404
    assert client.get("/v1/time").json()["now_ms"] == 5000


def test_history_alarms_topology_redundancy_and_energy_are_served() -> None:
    kernel, plant, _, client = station()
    samples = client.get("/v1/history", params={"tag": POD, "from_ms": 2000}).json()
    assert [s["time_ms"] for s in samples] == [2000, 3000, 4000]
    assert POD in client.get("/v1/history/tags").json()
    assert client.get("/v1/history", params={"tag": "no.such[X].point"}).status_code == 404
    assert client.get("/v1/history/energy").json() == []
    assert client.get("/v1/alarms").json() == []
    topology = client.get("/v1/topology").json()
    assert len(topology["trains"]) == 3 and len(topology["modules"]) > 30 and topology["wiring"]
    assert client.get("/v1/redundancy").json()["chillers"]["level"] == "N_PLUS_1"
    energy = client.get("/v1/energy").json()
    assert energy["pue"] > 1.0 and energy["quality"] == "good"
    plant.module("cooling.chw_plant", "CHW").inject("chiller_trip", chiller=1)
    kernel.run_for(3000)
    listed = client.get("/v1/alarms").json()
    assert [a["name"] for a in listed] == [CH1] and listed[0]["state"] == "ACTIVE_UNACKED"
    assert client.get("/v1/alarms/log").json()[-1]["kind"] == "raised"


@pytest.mark.req("ADC-SUP-004")
def test_every_write_needs_a_login() -> None:
    _, _, _, client = station()
    body = {"tag": CHWS, "value": 19.0, "reason": "trim"}
    assert client.post("/v1/commands", json=body).status_code == 401
    bad = {"Authorization": "Bearer not-a-session"}
    assert client.post("/v1/commands", json=body, headers=bad).status_code == 401
    assert client.post(f"/v1/alarms/acknowledge/{CH1}").status_code == 401
    wrong = client.post("/v1/sessions", json={"user": "operator-ola", "secret": "guess"})
    assert wrong.status_code == 401
    assert client.get(f"/v1/points/{CHWS}").json()["value"] == 18.0


@pytest.mark.req("ADC-SUP-003")
def test_an_operator_writes_through_the_command_service_and_it_is_logged() -> None:
    _, _, _, client = station()
    headers = login(client)
    answer = client.post(
        "/v1/commands", json={"tag": CHWS, "value": 19.0, "reason": "trim"}, headers=headers
    )
    assert answer.status_code == 200
    assert answer.json() == {"accepted": True, "code": "OK", "old": 18.0, "new": 19.0}
    entry = client.get("/v1/changes").json()[-1]
    assert (entry["tag"], entry["old"], entry["new"]) == (CHWS, 18.0, 19.0)
    assert (entry["actor"], entry["role"], entry["reason"]) == ("operator-ola", "operator", "trim")
    assert entry["time_ms"] == 5000 and entry["decision_ref"] is None
    assert [e["kind"] for e in client.get("/v1/audit").json()] == ["login"]


@pytest.mark.req("ADC-SUP-005")
def test_refusals_come_back_with_the_reason_code() -> None:
    _, _, _, client = station()
    headers = login(client)

    def refused(tag: str, value: Any, reason: str = "x") -> tuple[int, str]:
        body = {"tag": tag, "value": value, "reason": reason}
        answer = client.post("/v1/commands", json=body, headers=headers)
        return answer.status_code, answer.json()["detail"]

    assert refused(CHWS, 30.0) == (409, "OUT_OF_RANGE")
    assert refused(BREAKER, True) == (403, "TIER_FORBIDDEN")
    assert refused("no.such[X].point", 1.0) == (409, "UNKNOWN_TAG")
    assert refused(CHWS, 19.0, reason=" ") == (409, "REASON_REQUIRED")
    assert client.get(f"/v1/points/{CHWS}").json()["value"] == 18.0


def test_who_acts_is_taken_from_the_session_not_from_the_body() -> None:
    _, _, _, client = station()
    headers = login(client)
    body = {"tag": CHWS, "value": 19.0, "reason": "x", "actor": "admin-per", "role": "engineer"}
    assert client.post("/v1/commands", json=body, headers=headers).status_code == 422
    assert client.get("/v1/changes").json() == []


@pytest.mark.req("ADC-SUP-004")
def test_an_idle_session_is_view_only_over_the_api() -> None:
    kernel, _, _, client = station()
    headers = login(client)
    kernel.run_for(15 * 60_000)
    assert client.get("/v1/session", headers=headers).json()["role"] == "viewer"
    answer = client.post(
        "/v1/commands", json={"tag": CHWS, "value": 19.0, "reason": "x"}, headers=headers
    )
    assert (answer.status_code, answer.json()["detail"]) == (403, "ROLE_FORBIDDEN")


def test_an_operator_acknowledges_an_alarm() -> None:
    kernel, plant, _, client = station()
    plant.module("cooling.chw_plant", "CHW").inject("chiller_trip", chiller=1)
    kernel.run_for(3000)
    headers = login(client)
    answer = client.post(f"/v1/alarms/acknowledge/{CH1}", headers=headers)
    assert answer.status_code == 200 and answer.json()["state"] == "ACTIVE_ACKED"
    assert client.post(f"/v1/alarms/acknowledge/{CH1}", headers=headers).status_code == 409
    assert client.post("/v1/alarms/acknowledge/no-such", headers=headers).status_code == 404
    assert client.get("/v1/alarms/log").json()[-1]["actor"] == "operator-ola"


@pytest.mark.req("ADC-SUP-002")
def test_nothing_but_login_acknowledge_and_command_accepts_anything_but_get() -> None:
    _, _, supervisory, client = station()
    writing = sorted(
        route.path  # type: ignore[attr-defined]
        for route in create_app(supervisory).routes
        if getattr(route, "methods", {"GET"}) - {"GET", "HEAD"}
    )
    assert writing == [
        "/v1/alarms/acknowledge/{name:path}",
        "/v1/commands",
        "/v1/sessions",
        "/v1/sessions/end",
    ]
    for path in ("/v1/changes", "/v1/audit", "/v1/alarms/log"):
        assert client.delete(path).status_code == 405
        assert client.put(path, json=[]).status_code == 405
