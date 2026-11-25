"""Scenario files: a timeline of injected events and machine-checkable pass criteria (SDD 10)."""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentic_datacenter.core.state import state_hash

SCHEMA_VERSION = 1
LIBRARY = Path(__file__).parent / "library"


class ScenarioError(ValueError):
    """A scenario file is missing, unreadable or invalid."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class AuthorityChange(_Model):
    """A change to the mandate of a principal: the contracts it may propose from then on.

    ``contracts`` is the whole mandate after the change: ``all`` for every
    contract, a list for exactly those, an empty list to end it. ``reason`` is
    shown with the alarms, for example who lost access or who took over.
    ``by`` is who made the change. Both are kept in the mandate record a gate
    is given with each proposal (ADR 0031).
    """

    contracts: list[str] | Literal["all"]
    principal: str = "agent-1"
    reason: str = ""
    by: str = ""


class Event(_Model):
    """One injected event.

    Exactly one of ``inject`` (a fault or scenario input of a module),
    ``link`` (the supervisory network up or down), ``note`` (free text shown
    with the alarms), ``attempt`` (a connection or request tried across the
    zone model), ``replay`` (a used decision reference submitted again) or
    ``operator_write`` (a person at a workstation writes a tag through the
    command service), ``command_timeout`` (the next agent write goes
    unanswered, landed or not), ``agent_clock`` (the agent's own clock runs
    ``skew_s`` ahead), ``relay_request`` (an MMS request to a protection
    relay, put to the conduit and to the relay itself) or ``authority`` (the
    mandate of a principal ends, passes on or is narrowed) is given.
    """

    at_s: Annotated[int, Field(ge=0)]
    module: str | None = None
    inject: str | None = None
    params: dict[str, bool | int | float | str] = Field(default_factory=dict)
    link: Literal["up", "down"] | None = None
    note: str | None = None
    attempt: dict[str, str] | None = None
    replay: bool | None = None
    operator_write: dict[str, bool | int | float | str] | None = None
    command_timeout: dict[str, bool] | None = None
    agent_clock: dict[str, int] | None = None
    relay_request: dict[str, str] | None = None
    authority: AuthorityChange | None = None


class Criterion(_Model):
    """One pass criterion: a metric and the most, or the least, it may be."""

    metric: str
    max: float | None = None
    min: float | None = None


class Scenario(_Model):
    """One scripted scenario.

    ``planned_work`` lists the contracts for which a work permit exists during
    the scenario. The scripted operator approves nothing else that needs a
    person.
    """

    schema_version: Literal[1]
    #: ``OP`` operational and ``AD`` adversarial (SDD 10.1, 10.2); ``WF`` a what-if
    #: scenario, kept in the what-if package and out of this library (SDD 10.4).
    id: Annotated[str, Field(pattern=r"^(OP|AD|WF)-\d{2}$")]
    title: str
    track: Literal["A", "B", "C", "D"]
    duration_s: Annotated[int, Field(gt=0)]
    decision_every_s: Annotated[int, Field(gt=0)] = 300
    warmup_s: Annotated[int, Field(ge=0)] = 600
    objective: Literal["resilience", "energy"] = "resilience"
    timeline: tuple[Event, ...] = ()
    pass_criteria: tuple[Criterion, ...] = ()
    planned_work: tuple[str, ...] = ()
    expected: str = ""
    #: What the scenario needs of a bounded replay (ADR 0023): a branch at least
    #: this long, and at most this many proposals judged per run. A tier with
    #: unbounded replay ignores both.
    judge_horizon_s: Annotated[int, Field(gt=0)] | None = None
    judge_max: Annotated[int, Field(gt=0)] | None = None

    def judging(
        self, horizon_s: int | None, max_judged: int | None
    ) -> tuple[int | None, int | None]:
        """Return this scenario's replay bounds under a tier's *horizon_s* and *max_judged*."""
        if horizon_s is not None and self.judge_horizon_s is not None:
            horizon_s = max(horizon_s, self.judge_horizon_s)
        if max_judged is not None and self.judge_max is not None:
            max_judged = min(max_judged, self.judge_max)
        return horizon_s, max_judged

    def hash(self) -> str:
        """Return the hash that identifies this scenario in an evidence bundle."""
        return state_hash(self.model_dump(mode="json"))


def parse_scenario(data: object) -> Scenario:
    """Validate scenario *data*."""
    if not isinstance(data, dict):
        raise ScenarioError("a scenario must be a mapping")
    try:
        scenario = Scenario.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'scenario'}: {e['msg']}" for e in exc.errors()
        )
        raise ScenarioError(f"invalid scenario: {problems}") from exc
    for criterion in scenario.pass_criteria:
        if (criterion.max is None) == (criterion.min is None):
            raise ScenarioError(
                f"{scenario.id}: criterion {criterion.metric} needs exactly one of max or min"
            )
    for event in scenario.timeline:
        kinds = sum(
            x is not None
            for x in (
                *(event.inject, event.link, event.note, event.attempt),
                event.replay,
                event.operator_write,
                event.command_timeout,
                event.agent_clock,
                event.relay_request,
                event.authority,
            )
        )
        if kinds != 1 or (event.inject is not None) != (event.module is not None):
            raise ScenarioError(
                f"{scenario.id}: event at {event.at_s} s needs exactly one of inject (with "
                "module), link, note, attempt, replay, operator_write, command_timeout, "
                "agent_clock, relay_request or authority"
            )
        if event.at_s >= scenario.duration_s:
            raise ScenarioError(f"{scenario.id}: event at {event.at_s} s is after the end")
    return scenario


def load_scenario(source: str | Path) -> Scenario:
    """Read a scenario by id from the library, or from a path."""
    path = Path(source)
    if not path.suffix:
        path = LIBRARY / f"{source}.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ScenarioError(f"cannot read scenario {path}: {exc}") from exc
    try:
        return parse_scenario(data)
    except ScenarioError as exc:
        raise ScenarioError(f"{path}: {exc}") from exc


def library_ids() -> list[str]:
    """Return the ids of every scenario in the library, sorted."""
    return sorted(p.stem for p in LIBRARY.glob("*.yaml"))
