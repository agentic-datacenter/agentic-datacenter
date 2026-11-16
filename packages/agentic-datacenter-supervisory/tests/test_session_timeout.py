"""Roles and sessions (ADC-SUP-004, SDD 7.5)."""

from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.supervisory.command_service import CommandService
from agentic_datacenter.supervisory.logs import AppendOnlyLog
from agentic_datacenter.supervisory.points import PointDatabase
from agentic_datacenter.supervisory.sessions import (
    DEFAULT_USERS,
    IDLE_TIMEOUT_S,
    LEVELS,
    SessionManager,
)

REPO = Path(__file__).resolve().parents[3]
CHWS = "cooling.chw_plant[CHW].chws_sp_c"
MINUTE = 60_000


def system() -> tuple[Kernel, CommandService, SessionManager, AppendOnlyLog]:
    kernel = Kernel(seed=1)
    plant = build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    points = PointDatabase(kernel, plant)
    service = CommandService(kernel, points)
    audit = AppendOnlyLog(kernel, "audit")
    return kernel, service, SessionManager(kernel, DEFAULT_USERS, audit), audit


def password(user: str) -> str:
    return DEFAULT_USERS[user][1]


def test_there_are_four_permission_levels() -> None:
    assert sorted(LEVELS, key=LEVELS.__getitem__) == [
        "viewer", "operator", "engineer", "administrator",
    ]  # fmt: skip
    assert IDLE_TIMEOUT_S == 900


@pytest.mark.req("ADC-SUP-004")
def test_viewing_needs_no_login_and_every_write_does() -> None:
    _, service, sessions, _ = system()
    anonymous = sessions.actor(None)
    assert (anonymous.name, anonymous.role) == ("anonymous", "viewer")
    assert service.write(CHWS, 19.0, anonymous, reason="x").code == "ROLE_FORBIDDEN"
    token = sessions.login("operator-ola", password("operator-ola"))
    actor = sessions.actor(token)
    assert (actor.name, actor.role) == ("operator-ola", "operator")
    assert service.write(CHWS, 19.0, actor, reason="x").accepted


@pytest.mark.req("ADC-SUP-004")
def test_session_reverts_to_view_only_after_fifteen_minutes_idle() -> None:
    kernel, service, sessions, audit = system()
    token = sessions.login("operator-ola", password("operator-ola"))
    kernel.run_for(14 * MINUTE)
    assert sessions.actor(token).role == "operator", "fourteen minutes idle is still a session"
    kernel.run_for(14 * MINUTE)
    assert sessions.actor(token).role == "operator", "activity starts the fifteen minutes again"
    kernel.run_for(15 * MINUTE)
    actor = sessions.actor(token)
    assert (actor.name, actor.role) == ("operator-ola", "viewer")
    assert service.write(CHWS, 19.0, actor, reason="x").code == "ROLE_FORBIDDEN"
    kernel.run_for(MINUTE)
    assert sessions.actor(token).role == "viewer", "it does not come back by itself"
    timeouts = [e for e in audit.entries() if e["kind"] == "session_timeout"]
    assert len(timeouts) == 1 and timeouts[0]["user"] == "operator-ola"
    again = sessions.login("operator-ola", password("operator-ola"))
    assert again != token and sessions.actor(again).role == "operator"


@pytest.mark.req("ADC-SUP-004")
def test_looking_at_a_session_is_not_activity() -> None:
    kernel, _, sessions, _ = system()
    token = sessions.login("engineer-kari", password("engineer-kari"))
    kernel.run_for(10 * MINUTE)
    assert sessions.describe(token)["role"] == "engineer"
    kernel.run_for(5 * MINUTE)
    assert sessions.describe(token)["role"] == "viewer"


def test_wrong_secret_unknown_user_and_unknown_token_are_refused_and_logged() -> None:
    _, _, sessions, audit = system()
    with pytest.raises(PermissionError):
        sessions.login("operator-ola", "guess")
    with pytest.raises(PermissionError):
        sessions.login("nobody", "guess")
    with pytest.raises(PermissionError):
        sessions.actor("not-a-token")
    kinds = [e["kind"] for e in audit.entries()]
    assert kinds == ["login_failed", "login_failed"]
    assert "guess" not in str(audit.entries())


def test_logout_ends_the_session() -> None:
    _, _, sessions, audit = system()
    token = sessions.login("operator-ola", password("operator-ola"))
    sessions.logout(token)
    with pytest.raises(PermissionError):
        sessions.actor(token)
    assert [e["kind"] for e in audit.entries()] == ["login", "logout"]


def test_sessions_are_state_and_tokens_are_reproducible() -> None:
    kernel, _, sessions, _ = system()
    saved, digest = kernel.snapshot(), kernel.state_hash()
    token = sessions.login("operator-ola", password("operator-ola"))
    assert kernel.state_hash() != digest
    kernel.restore(saved)
    with pytest.raises(PermissionError):
        sessions.actor(token)
    assert kernel.state_hash() == digest
    assert sessions.login("operator-ola", password("operator-ola")) == token
    other: Any = system()
    assert other[2].login("operator-ola", password("operator-ola")) == token
