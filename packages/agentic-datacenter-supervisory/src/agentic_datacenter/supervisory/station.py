"""The supervisory layer of one plant, assembled (SDD 7.5, 8.3)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agentic_datacenter.core.registry import Plant
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.supervisory.alarms import AlarmEngine, default_alarms
from agentic_datacenter.supervisory.command_service import CommandService
from agentic_datacenter.supervisory.historian import Historian
from agentic_datacenter.supervisory.logs import AppendOnlyLog
from agentic_datacenter.supervisory.overview import Overview
from agentic_datacenter.supervisory.points import PointDatabase
from agentic_datacenter.supervisory.sessions import DEFAULT_USERS, SessionManager


@dataclass(frozen=True)
class Supervisory:
    """Point database, command service, alarms, historian, sessions and the audit log."""

    kernel: Kernel
    plant: Plant
    points: PointDatabase
    service: CommandService
    alarms: AlarmEngine
    historian: Historian
    sessions: SessionManager
    audit: AppendOnlyLog
    overview: Overview


def build_supervisory(
    kernel: Kernel,
    plant: Plant,
    writes_per_minute: int = 10,
    users: Mapping[str, tuple[str, str]] = DEFAULT_USERS,
    history_retention_s: int = 3600,
) -> Supervisory:
    """Build the supervisory layer on *plant*."""
    points = PointDatabase(kernel, plant)
    audit = AppendOnlyLog(kernel, "audit")
    return Supervisory(
        kernel,
        plant,
        points,
        CommandService(kernel, points, writes_per_minute),
        AlarmEngine(kernel, points, default_alarms(points)),
        Historian(kernel, points, retention_s=history_retention_s),
        SessionManager(kernel, users, audit),
        audit,
        Overview(points),
    )
