"""Roles and sessions (SDD 7.5, ADC-SUP-004).

Four permission levels. Viewing needs no login; every write does. A session
that has been idle for fifteen minutes reverts to view-only and stays so until
its user logs in again.

The users and secrets here exist only inside the simulator. They are fixed and
public so that a run can be reproduced; they are not credentials for anything.
"""

from __future__ import annotations

from collections.abc import Mapping

from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.supervisory.command_service import Actor
from agentic_datacenter.supervisory.logs import AppendOnlyLog

#: The four permission levels, lowest first.
LEVELS = {"viewer": 0, "operator": 1, "engineer": 2, "administrator": 3}
IDLE_TIMEOUT_S = 900
ANONYMOUS = Actor("anonymous", "viewer")
#: Simulator-only users: name -> (role, secret).
DEFAULT_USERS: dict[str, tuple[str, str]] = {
    "operator-ola": ("operator", "simulator-only-ola"),
    "operator-eva": ("operator", "simulator-only-eva"),
    "engineer-kari": ("engineer", "simulator-only-kari"),
    "admin-per": ("administrator", "simulator-only-per"),
}


class SessionManager:
    """Logs users in and says, at any moment, what role a session has."""

    def __init__(
        self,
        kernel: Kernel,
        users: Mapping[str, tuple[str, str]],
        audit: AppendOnlyLog,
        idle_timeout_s: int = IDLE_TIMEOUT_S,
    ) -> None:
        """Create the manager for *users* (name -> role and secret).

        Raises:
            ValueError: If a user has a role that is not a permission level.
        """
        for name, (role, _) in users.items():
            if role not in LEVELS:
                raise ValueError(f"user {name!r} has unknown role {role!r}")
        self._kernel, self._users, self._audit = kernel, dict(users), audit
        self._idle_ms = idle_timeout_s * 1000
        self._tokens = kernel.rng.stream("supervisory.sessions")
        self._sessions: dict[str, dict[str, JsonValue]] = {}
        kernel.state.register("supervisory.sessions", self, tracked=True)

    def login(self, user: str, secret: str) -> str:
        """Start a session and return its token.

        Raises:
            PermissionError: If the user is unknown or the secret is wrong.
        """
        known = self._users.get(user)
        if known is None or known[1] != secret:
            self._audit.append("login_failed", user=user)
            raise PermissionError("unknown user or wrong secret")
        token = f"{self._tokens.getrandbits(128):032x}"
        self._sessions[token] = {
            "user": user, "role": known[0], "last_ms": self._kernel.clock.now_ms,
            "timed_out": False,
        }  # fmt: skip
        self._kernel.state.touch("supervisory.sessions")
        self._audit.append("login", user=user, role=known[0])
        return token

    def _current(self, token: str) -> dict[str, JsonValue]:
        session = self._sessions.get(token)
        if session is None:
            raise PermissionError("no such session")
        idle = self._kernel.clock.now_ms - int(str(session["last_ms"]))
        if not session["timed_out"] and idle >= self._idle_ms:
            session["timed_out"] = True
            self._kernel.state.touch("supervisory.sessions")
            self._audit.append("session_timeout", user=session["user"], role=session["role"])
        return session

    def actor(self, token: str | None) -> Actor:
        """Return who a request with *token* acts as, and count it as activity.

        Without a token the request is anonymous and may only view. A session
        idle for fifteen minutes is view-only.

        Raises:
            PermissionError: If the token is not a session.
        """
        if token is None:
            return ANONYMOUS
        session = self._current(token)
        if session["timed_out"]:
            return Actor(str(session["user"]), "viewer")
        session["last_ms"] = self._kernel.clock.now_ms
        self._kernel.state.touch("supervisory.sessions")
        return Actor(str(session["user"]), str(session["role"]))

    def describe(self, token: str) -> dict[str, JsonValue]:
        """Return the user, the role in effect and the idle time, without counting as activity.

        Raises:
            PermissionError: If the token is not a session.
        """
        session = self._current(token)
        return {
            "user": session["user"],
            "role": "viewer" if session["timed_out"] else session["role"],
            "idle_ms": self._kernel.clock.now_ms - int(str(session["last_ms"])),
        }

    def logout(self, token: str) -> None:
        """End a session.

        Raises:
            PermissionError: If the token is not a session.
        """
        session = self._sessions.pop(token, None)
        if session is None:
            raise PermissionError("no such session")
        self._kernel.state.touch("supervisory.sessions")
        self._audit.append("logout", user=session["user"])

    def snapshot(self) -> JsonValue:
        """Return every session."""
        return {token: dict(session) for token, session in self._sessions.items()}

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("session snapshot must be a mapping")
        self._sessions = {
            token: dict(session) for token, session in state.items() if isinstance(session, Mapping)
        }
