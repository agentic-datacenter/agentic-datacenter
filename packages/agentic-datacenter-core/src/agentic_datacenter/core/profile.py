"""Facility profiles.

A profile is the facility: which modules exist, in how many instances, with
which parameters, and how their ports are connected. Changing the facility
means changing a profile, never the code (SDD 3).

Every parameter value carries where it came from: a ``source``, or
``assumed: true`` (ADC-PRV-004).
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agentic_datacenter.core.registry import Connection, InstanceSpec, ModuleRegistry, Plant
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue, state_hash

SCHEMA_VERSION = 1
_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_]*)\}")
Rows = list[dict[str, str]]


class ProfileError(ValueError):
    """A profile is missing, unreadable or invalid."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Param(_Model):
    """One parameter value and its provenance."""

    value: bool | int | float | str | list[float]
    unit: str = ""
    source: str | None = None
    assumed: bool | None = None

    @model_validator(mode="after")
    def _exactly_one_tag(self) -> Param:
        has_source = bool(self.source and self.source.strip())
        if self.source is not None and not has_source:
            raise ValueError("source must not be empty")
        if self.assumed is False:
            raise ValueError("assumed, when present, must be true")
        if has_source == bool(self.assumed):
            raise ValueError("give exactly one of `source` or `assumed: true`")
        return self


class ModuleUse(_Model):
    """The instances of one module in the facility."""

    id: str
    instances: Annotated[list[str], Field(min_length=1)] | None = None
    for_each: str | None = None
    instance: str | None = None
    stub: bool = False
    params: dict[str, Param] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_way_to_name_instances(self) -> ModuleUse:
        if (self.instances is None) == (self.for_each is None):
            raise ValueError("give exactly one of `instances` or `for_each`")
        if self.for_each is not None and self.instance is None:
            raise ValueError("`for_each` needs an `instance` name pattern")
        if self.instances is not None and len(set(self.instances)) != len(self.instances):
            repeated = sorted({i for i in self.instances if self.instances.count(i) > 1})
            raise ValueError(f"instances listed more than once: {', '.join(repeated)}")
        return self


class ConnectionRule(_Model):
    """One connection, or one per key or per table row."""

    consumer: str
    provider: str
    for_each: str | None = None
    rows: str | Rows | None = Field(default=None, alias="with")

    @model_validator(mode="after")
    def _one_expansion(self) -> ConnectionRule:
        if self.for_each is not None and self.rows is not None:
            raise ValueError("give at most one of `for_each` or `with`")
        return self


class Profile(_Model):
    """A facility profile."""

    schema_version: Literal[1]
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    description: str = ""
    site: str
    key_sets: dict[str, list[str]] = Field(default_factory=dict)
    tables: dict[str, Rows] = Field(default_factory=dict)
    module_uses: list[ModuleUse] = Field(alias="modules")
    connection_rules: list[ConnectionRule] = Field(default_factory=list, alias="connections")
    economics: dict[str, Param] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _references_resolve(self) -> Profile:
        for name, keys in self.key_sets.items():
            if len(set(keys)) != len(keys):
                raise ValueError(f"key set {name!r} repeats a key")
        for use in self.module_uses:
            if use.for_each is not None and use.for_each not in self.key_sets:
                raise ValueError(f"module {use.id}: unknown key set {use.for_each!r}")
        for rule in self.connection_rules:
            if rule.for_each is not None and rule.for_each not in self.key_sets:
                raise ValueError(f"connection {rule.consumer}: unknown key set {rule.for_each!r}")
            if isinstance(rule.rows, str) and rule.rows not in self.tables:
                raise ValueError(f"connection {rule.consumer}: unknown table {rule.rows!r}")
        self.instances()
        self.connections()
        return self

    def _rows(self, for_each: str | None, rows: str | Rows | None) -> Rows:
        if for_each is not None:
            return [{for_each: key} for key in self.key_sets[for_each]]
        if isinstance(rows, str):
            return self.tables[rows]
        return rows if rows is not None else [{}]

    @staticmethod
    def _fill(template: str, row: Mapping[str, str]) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group(1)
            if name not in row:
                raise ValueError(f"{template!r}: nothing to put in place of {{{name}}}")
            return row[name]

        return _PLACEHOLDER.sub(replace, template)

    def instances(self) -> list[InstanceSpec]:
        """Return every module instance of the facility."""
        keys = {name: tuple(values) for name, values in self.key_sets.items()}
        out: list[InstanceSpec] = []
        for use in self.module_uses:
            params: dict[str, JsonValue] = {name: p.value for name, p in use.params.items()}
            if use.instances is not None:
                names = list(use.instances)
            else:
                assert use.instance is not None
                names = [self._fill(use.instance, row) for row in self._rows(use.for_each, None)]
            out.extend(
                InstanceSpec(use.id, n, params=params, keys=keys, stub=use.stub) for n in names
            )
        return out

    def connections(self) -> list[Connection]:
        """Return every connection of the facility."""
        return [
            Connection(self._fill(rule.consumer, row), self._fill(rule.provider, row))
            for rule in self.connection_rules
            for row in self._rows(rule.for_each, rule.rows)
        ]

    def with_param(
        self,
        module_id: str,
        name: str,
        value: bool | int | float | str,
        instance: str | None = None,
    ) -> Profile:
        """Return a copy in which parameter *name* of module *module_id* is *value*.

        For sensitivity runs. The value is tagged ``assumed``. With *instance*,
        only that instance changes: it is taken out of its use into a use of its
        own (ADR 0033).

        Raises:
            ValueError: If the profile has no such module, or no such instance of it.
        """
        if not any(use.id == module_id for use in self.module_uses):
            raise ValueError(f"profile {self.name} has no module {module_id!r}")
        param = Param(value=value, assumed=True)
        if instance is None:
            uses = [
                use.model_copy(update={"params": {**use.params, name: param}})
                if use.id == module_id
                else use
                for use in self.module_uses
            ]
            return self.model_copy(update={"module_uses": uses})
        uses = []
        found = False
        for use in self.module_uses:
            names = self._use_names(use) if use.id == module_id else []
            if instance not in names:
                uses.append(use)
                continue
            found = True
            rest = [n for n in names if n != instance]
            if rest:
                uses.append(
                    use.model_copy(update={"instances": rest, "for_each": None, "instance": None})
                )
            uses.append(
                use.model_copy(
                    update={
                        "instances": [instance], "for_each": None, "instance": None,
                        "params": {**use.params, name: param},
                    }
                )
            )  # fmt: skip
        if not found:
            raise ValueError(f"profile {self.name} has no instance {module_id}[{instance}]")
        return self.model_copy(update={"module_uses": uses})

    def _use_names(self, use: ModuleUse) -> list[str]:
        if use.instances is not None:
            return list(use.instances)
        assert use.instance is not None
        return [self._fill(use.instance, row) for row in self._rows(use.for_each, None)]

    def hash(self) -> str:
        """Return the hash that identifies this profile in an evidence bundle."""
        return state_hash(self.model_dump(mode="json", by_alias=True))


def parse_profile(data: object) -> Profile:
    """Validate profile *data*.

    Raises:
        ProfileError: If the data does not satisfy the profile schema, or was
            written for a newer schema version.
    """
    if not isinstance(data, Mapping):
        raise ProfileError("a profile must be a mapping")
    version = data.get("schema_version")
    if isinstance(version, int) and version > SCHEMA_VERSION:
        raise ProfileError(f"schema_version {version} is newer than this reader ({SCHEMA_VERSION})")
    try:
        return Profile.model_validate(dict(data))
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'profile'}: {e['msg']}" for e in exc.errors()
        )
        raise ProfileError(f"invalid profile: {problems}") from exc


def load_profile(path: Path) -> Profile:
    """Read and validate the profile file at *path*.

    Raises:
        ProfileError: If the file is missing, is not YAML, or is invalid.
    """
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileError(f"cannot read profile {path}: {exc}") from exc
    try:
        return parse_profile(data)
    except ProfileError as exc:
        raise ProfileError(f"{path}: {exc}") from exc


def build_plant(profile: Profile, kernel: Kernel, registry: ModuleRegistry) -> Plant:
    """Build the facility of *profile* on *kernel* from the modules in *registry*."""
    return registry.build(kernel, profile.instances(), profile.connections())
