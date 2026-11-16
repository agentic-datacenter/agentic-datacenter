"""The what-if request and its validation (ADR 0019).

A request names a what-if scenario from this package's library, the seed, the
change (one contract, its one numeric argument and the target value), which
branches to play, an optional energy price and the bounds of the policy
analysis. It names no file: the profile and the contract library are chosen by
whoever runs the request, so a request sent to the job API cannot point the
simulator at an arbitrary path.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from agentic_datacenter.core.state import state_hash
from agentic_datacenter.scenarios.scenario import Scenario, ScenarioError, parse_scenario

SCHEMA_VERSION = 1
LIBRARY = Path(__file__).parent / "library"
Branch = Literal["baseline", "physical", "governed"]
BRANCHES: tuple[Branch, ...] = ("baseline", "physical", "governed")


class SpecError(ValueError):
    """A what-if request is invalid, or does not fit the facility or the contract."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Change(_Model):
    """The proposed change: one contract instance and the value it should reach.

    ``expected_start`` is what the requester believes the present value is; the
    run refuses to go on when the plant says otherwise.
    """

    contract_id: Annotated[str, Field(min_length=1, max_length=120)]
    argument: Annotated[str, Field(min_length=1, max_length=60)]
    target: float
    expected_start: float | None = None

    @field_validator("target", "expected_start")
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("must be a finite number")
        return value


class EnergyPrice(_Model):
    """A price per kWh, supplied by the requester. Agentic Datacenter never assumes one."""

    per_kwh: Annotated[float, Field(gt=0.0)]
    currency: Annotated[str, Field(pattern=r"^[A-Z]{3}$")]


class PolicyOptions(_Model):
    """Whether to run REMORA's policy analysis, and its search bounds."""

    enabled: bool = True
    max_depth: Annotated[int, Field(ge=1, le=6)] = 4
    max_evaluations: Annotated[int, Field(ge=1, le=200_000)] = 20_000


class WhatIfSpec(_Model):
    """One what-if request."""

    schema_version: Literal[1] = 1
    scenario: Annotated[str, Field(pattern=r"^WF-\d{2}$")] = "WF-01"
    seed: Annotated[int, Field(ge=0)] = 1
    duration_s: Annotated[int, Field(gt=0)] | None = None
    change: Change
    energy_price: EnergyPrice | None = None
    branches: tuple[Branch, ...] = BRANCHES
    policy: PolicyOptions = PolicyOptions()

    @field_validator("branches")
    @classmethod
    def _branches(cls, value: tuple[Branch, ...]) -> tuple[Branch, ...]:
        if "baseline" not in value:
            raise ValueError("the baseline branch is required: savings are measured against it")
        if len(set(value)) != len(value):
            raise ValueError("a branch is named twice")
        return tuple(b for b in BRANCHES if b in value)

    def hash(self) -> str:
        """Return the hash that identifies this request."""
        return state_hash(self.model_dump(mode="json"))


def parse_spec(data: object) -> WhatIfSpec:
    """Validate a what-if request.

    Raises:
        SpecError: Naming every field that is wrong.
    """
    if not isinstance(data, dict):
        raise SpecError("a what-if request must be a JSON object")
    try:
        return WhatIfSpec.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'request'}: {e['msg']}" for e in exc.errors()
        )
        raise SpecError(f"invalid what-if request: {problems}") from exc


def load_whatif_scenario(scenario_id: str) -> Scenario:
    """Return a what-if scenario from this package's library.

    Raises:
        SpecError: If there is no such scenario or it is invalid.
    """
    path = LIBRARY / f"{scenario_id}.yaml"
    if not path.is_file():
        known = ", ".join(whatif_ids()) or "none"
        raise SpecError(f"no what-if scenario {scenario_id}; known: {known}")
    try:
        return parse_scenario(yaml.safe_load(path.read_text(encoding="utf-8")))
    except (ScenarioError, yaml.YAMLError) as exc:
        raise SpecError(f"{path.name}: {exc}") from exc


def whatif_ids() -> list[str]:
    """Return the ids of the what-if scenarios, sorted."""
    return sorted(p.stem for p in LIBRARY.glob("WF-*.yaml"))
