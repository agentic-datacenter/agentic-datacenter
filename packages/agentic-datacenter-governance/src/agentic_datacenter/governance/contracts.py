"""Intent contracts: typed, bounded descriptions of what an agent may propose (SDD 9.4)."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agentic_datacenter.supervisory.points import PointDatabase

SCHEMA_VERSION = 1
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")


class ContractError(ValueError):
    """A contract is missing, unreadable, invalid, or does not fit the facility."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Argument(_Model):
    """One argument of a contract.

    ``authoritative: false`` marks an input the agent supplies that nothing is
    decided on, such as a forecast: it is stored with the proposal as a claim.
    """

    type: Literal["number", "key", "choice", "text"]
    key_set: str | None = None
    choices: tuple[str, ...] | None = None
    authoritative: bool = True


class Bounds(_Model):
    """Limits on one write, tighter than or equal to the point's own range."""

    min: float
    max: float
    max_step: float | None = None
    unit: str = ""


class Write(_Model):
    """One write of a contract: a tag and where its value comes from."""

    tag: str
    value: str | None = None
    const: bool | float | str | None = None
    bounds: Bounds | None = None

    @model_validator(mode="after")
    def _one_source(self) -> Write:
        if (self.value is None) == (self.const is None):
            raise ValueError(f"{self.tag}: give exactly one of `value` or `const`")
        return self


class Premise(_Model):
    """A fact about plant state the contract requires, with a freshness limit."""

    expr: str
    max_age_s: Annotated[float, Field(gt=0)]
    when: Literal["always", "increase", "decrease"] = "always"
    invariant: str = ""


class Rate(_Model):
    """How often a contract may be applied."""

    max_per_hour: Annotated[int, Field(gt=0)]


class Cumulative(_Model):
    """How far one tag may be moved in total inside a window, across all contracts."""

    window_h: Annotated[float, Field(gt=0)]
    max_total_delta: Annotated[float, Field(gt=0)]


class Limits(_Model):
    """Rate and cumulative limits."""

    rate: Rate | None = None
    cumulative: Cumulative | None = None


class Rollback(_Model):
    """When an applied contract is undone, and how."""

    trigger: str
    action: Literal["restore_previous"]


class Contract(_Model):
    """One intent contract."""

    schema_version: Literal[1]
    id: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_.]*\.v\d+$")]
    title: str
    risk_tier: Literal["R0", "R1", "R2", "R3"]
    arguments: dict[str, Argument] = Field(default_factory=dict)
    writes: tuple[Write, ...] = ()
    premises: tuple[Premise, ...] = ()
    limits: Limits = Limits()
    rollback: Rollback | None = None
    approval: Literal["none", "one_operator", "two_person", "not_available"]

    @model_validator(mode="after")
    def _consistent(self) -> Contract:
        if self.risk_tier == "R3" and (self.writes or self.approval != "not_available"):
            raise ValueError("an R3 contract has no writes and is never available")
        if self.risk_tier != "R3" and self.approval == "not_available":
            raise ValueError("only an R3 contract is not available")
        if self.risk_tier == "R2" and self.approval == "none":
            raise ValueError("an R2 contract needs human approval")
        used = set()
        for write in self.writes:
            used |= set(_PLACEHOLDER.findall(write.tag))
            if write.value is not None:
                used.add(write.value)
        unknown = sorted(used - self.arguments.keys())
        if unknown:
            raise ValueError(f"writes use undeclared argument(s): {', '.join(unknown)}")
        return self

    def safe_direction(self) -> str | None:
        """Return the direction a step goes back toward safety, if the contract has one.

        A reversible contract whose premises guard exactly one direction of
        movement (``when: increase``, say) treats the other direction as the
        way back. Every numeric write must be bounded; otherwise there is none.
        """
        guarded = {p.when for p in self.premises if p.when != "always"}
        if self.rollback is None or len(guarded) != 1:
            return None
        if not self.writes or any(w.value is None or w.bounds is None for w in self.writes):
            return None
        return "decrease" if guarded == {"increase"} else "increase"


def parse_contract(data: object) -> Contract:
    """Validate contract *data*."""
    if not isinstance(data, dict):
        raise ContractError("a contract must be a mapping")
    version = data.get("schema_version")
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise ContractError(f"schema_version {version} is newer than this reader")
    try:
        return Contract.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'contract'}: {e['msg']}" for e in exc.errors()
        )
        raise ContractError(f"invalid contract: {problems}") from exc


class ContractLibrary:
    """The contracts an agent may propose."""

    def __init__(self, contracts: list[Contract]) -> None:
        """Create a library; ids must be unique."""
        ids = [c.id for c in contracts]
        repeated = sorted({i for i in ids if ids.count(i) > 1})
        if repeated:
            raise ContractError(f"contract id(s) used more than once: {', '.join(repeated)}")
        self._contracts = {c.id: c for c in sorted(contracts, key=lambda c: c.id)}

    @classmethod
    def load(cls, directory: Path) -> ContractLibrary:
        """Read every ``*.yaml`` in *directory*."""
        contracts = []
        for path in sorted(directory.glob("*.yaml")):
            try:
                contracts.append(parse_contract(yaml.safe_load(path.read_text(encoding="utf-8"))))
            except (OSError, yaml.YAMLError, ContractError) as exc:
                raise ContractError(f"{path}: {exc}") from exc
        if not contracts:
            raise ContractError(f"no contracts found in {directory}")
        return cls(contracts)

    def ids(self) -> list[str]:
        """Return every contract id, sorted."""
        return list(self._contracts)

    def get(self, contract_id: str) -> Contract | None:
        """Return a contract, or None when there is none with that id."""
        return self._contracts.get(contract_id)

    def check_against(self, points: PointDatabase, key_sets: dict[str, tuple[str, ...]]) -> None:
        """Refuse a library that does not fit the facility.

        Every tag a contract can write must exist for every allowed argument
        value, must be tier T2 or T3 (never T0 or T1, ADC-GOV-005), and its
        contract bounds must lie inside the point's own range.

        Raises:
            ContractError: Naming the first contract and tag that does not fit.
        """
        for contract_id in self._contracts:
            problem = self.problem(contract_id, points, key_sets)
            if problem is not None:
                raise ContractError(f"{contract_id}: {problem}")

    def problem(
        self, contract_id: str, points: PointDatabase, key_sets: dict[str, tuple[str, ...]]
    ) -> str | None:
        """Return why one contract does not fit the facility, or ``None`` when it does.

        The checks are those of :meth:`check_against`, for one contract.
        """
        contract = self._contracts[contract_id]
        tags = set(points.tags())
        for write in contract.writes:
            try:
                expanded = _expand(write.tag, contract, key_sets)
            except ContractError as exc:
                return str(exc).removeprefix(f"{contract_id}: ")
            for tag in expanded:
                if tag not in tags:
                    return f"no such point {tag}"
                decl = points.declaration(tag)
                if decl.tier not in ("T2", "T3"):
                    return f"{tag} is tier {decl.tier} and can never be written"
                if contract.risk_tier == "R1" and decl.tier != "T3":
                    return "an R1 contract may write T3 only"
                bounds, limits = write.bounds, decl.range
                if bounds and limits and not limits[0] <= bounds.min <= bounds.max <= limits[1]:
                    return f"bounds on {tag} exceed its range"
        return None

    def subset(self, contract_ids: list[str]) -> ContractLibrary:
        """Return the library of the contracts *contract_ids* only (ADR 0033)."""
        return ContractLibrary([self._contracts[c] for c in contract_ids])


def _expand(template: str, contract: Contract, key_sets: dict[str, tuple[str, ...]]) -> list[str]:
    """Return every tag a templated write can address."""
    tags = [template]
    for name in _PLACEHOLDER.findall(template):
        argument = contract.arguments[name]
        if argument.type == "key":
            values: tuple[str, ...] = key_sets.get(argument.key_set or "", ())
        else:
            values = argument.choices or ()
        if not values:
            raise ContractError(f"{contract.id}: argument {name} has no allowed values")
        tags = [t.replace("{" + name + "}", v) for t in tags for v in values]
    return tags


def fill(template: str, arguments: dict[str, str]) -> str:
    """Put argument values into a templated tag or expression."""
    return _PLACEHOLDER.sub(lambda m: arguments.get(m.group(1), m.group(0)), template)
