"""The operator API: the read API and the door to the Supervisory Command Service (SDD 8.3).

Reading needs no login. The three things that are not reads (logging in,
acknowledging an alarm, asking the command service for a write) are the only
routes that accept anything but GET. Who a request acts as is taken from its
session, never from its body.

The same application serves both run modes. Transport security (mutual TLS)
belongs to the deployment in ``compose`` mode; in ``inproc`` mode the
application is called directly. The API does not move simulated time.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Annotated, Any

from fastapi import FastAPI, Header, HTTPException, Query
from pydantic import BaseModel, ConfigDict

from agentic_datacenter.supervisory.command_service import Actor
from agentic_datacenter.supervisory.station import Supervisory

API_VERSION = "v1"
Auth = Annotated[str | None, Header()]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Login(_Body):
    """A login request."""

    user: str
    secret: str


class Command(_Body):
    """A write request to the Supervisory Command Service."""

    tag: str
    value: bool | int | float | str
    reason: str
    decision_ref: str | None = None


def _token(authorization: str | None) -> str | None:
    if authorization is None:
        return None
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "use 'Authorization: Bearer <token>'")
    return token


def create_app(station: Supervisory) -> FastAPI:
    """Return the API of *station*."""
    app = FastAPI(
        title="Agentic Datacenter supervisory API",
        version=API_VERSION,
        docs_url=None,
        redoc_url=None,
    )
    points, overview = station.points, station.overview

    def actor(authorization: str | None, must_login: bool = False) -> Actor:
        token = _token(authorization)
        if token is None and must_login:
            raise HTTPException(401, "log in first")
        try:
            return station.sessions.actor(token)
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc

    def point(tag: str) -> dict[str, Any]:
        if tag not in points.tags():
            raise HTTPException(404, f"no such point: {tag}")
        return asdict(points.read(tag))

    # -- reads --------------------------------------------------------------------------

    @app.get("/v1/time")
    def time() -> dict[str, Any]:
        quality, polled_ms = points.freshness()
        return {"now_ms": station.kernel.clock.now_ms, "quality": quality, "polled_ms": polled_ms}

    @app.get("/v1/points")
    def list_points(prefix: str = "") -> list[dict[str, Any]]:
        return [point(tag) for tag in points.tags() if tag.startswith(prefix)]

    @app.get("/v1/points/{tag:path}")
    def one_point(tag: str) -> dict[str, Any]:
        return point(tag)

    @app.get("/v1/history")
    def history(
        tag: str, from_ms: int | None = None, to_ms: int | None = None
    ) -> list[dict[str, Any]]:
        try:
            return [asdict(s) for s in station.historian.history(tag, from_ms, to_ms)]
        except KeyError as exc:
            raise HTTPException(404, str(exc.args[0])) from exc

    @app.get("/v1/history/energy")
    def energy_history(from_ms: int | None = None) -> list[dict[str, Any]]:
        return list(station.historian.energy_records(from_ms))

    @app.get("/v1/history/tags")
    def history_tags() -> list[str]:
        return list(station.historian.realtime_tags)

    @app.get("/v1/alarms")
    def alarms() -> list[dict[str, Any]]:
        return [asdict(a) for a in station.alarms.active()]

    @app.get("/v1/alarms/log")
    def alarm_log(since_seq: Annotated[int, Query(ge=0)] = 0) -> list[dict[str, Any]]:
        return list(station.alarms.log.entries(since_seq))

    @app.get("/v1/topology")
    def topology() -> dict[str, Any]:
        trains = {
            record.tag.rsplit(".", 1)[0]: {"state": record.value, "quality": record.quality}
            for record in points.find("electrical.power_train", "state")
        }
        modules = [
            {"name": name, "module": manifest.id, "fidelity": manifest.fidelity}
            for name, manifest, _ in station.plant.instances()
        ]
        wiring = [list(edge) for edge in station.plant.wiring()]
        return {"trains": trains, "modules": modules, "wiring": wiring}

    @app.get("/v1/redundancy")
    def redundancy() -> dict[str, Any]:
        return {
            name: {
                "available": r.available,
                "required": r.required,
                "level": r.level_name,
                "quality": r.quality,
            }
            for name, r in overview.redundancy().items()
        }

    @app.get("/v1/energy")
    def energy() -> dict[str, Any]:
        return dict(overview.energy())

    @app.get("/v1/changes")
    def changes() -> list[dict[str, Any]]:
        return list(station.service.change_log())

    @app.get("/v1/audit")
    def audit(since_seq: Annotated[int, Query(ge=0)] = 0) -> list[dict[str, Any]]:
        return list(station.audit.entries(since_seq))

    @app.get("/v1/session")
    def session(authorization: Auth = None) -> dict[str, Any]:
        token = _token(authorization)
        if token is None:
            return {"user": "anonymous", "role": "viewer", "idle_ms": 0}
        try:
            return dict(station.sessions.describe(token))
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc

    # -- not reads ------------------------------------------------------------------------

    @app.post("/v1/sessions")
    def login(body: Login) -> dict[str, Any]:
        try:
            return {"token": station.sessions.login(body.user, body.secret)}
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc

    @app.post("/v1/sessions/end")
    def logout(authorization: Auth = None) -> dict[str, Any]:
        token = _token(authorization)
        try:
            station.sessions.logout(token or "")
        except PermissionError as exc:
            raise HTTPException(401, str(exc)) from exc
        return {"ended": True}

    @app.post("/v1/alarms/acknowledge/{name:path}")
    def acknowledge(name: str, authorization: Auth = None) -> dict[str, Any]:
        who = actor(authorization, must_login=True)
        if who.role == "viewer":
            raise HTTPException(403, "ROLE_FORBIDDEN")
        try:
            station.alarms.acknowledge(name, who.name)
        except KeyError as exc:
            raise HTTPException(404, f"no such alarm: {name}") from exc
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        return {"alarm": name, "state": station.alarms.state(name)}

    @app.post("/v1/commands")
    def command(body: Command, authorization: Auth = None) -> dict[str, Any]:
        who = actor(authorization, must_login=True)
        result = station.service.write(body.tag, body.value, who, body.reason, body.decision_ref)
        if not result.accepted:
            status = 403 if result.code in ("ROLE_FORBIDDEN", "TIER_FORBIDDEN") else 409
            raise HTTPException(status, result.code)
        return asdict(result)

    return app
