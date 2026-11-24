"""Facility bundles: one's own data center as a directory of files (ADR 0033).

A bundle is a directory with ``datacenter.yaml`` at its root. That file names the
facility and lists the files it includes. Each included file holds part of the
facility: key sets, tables, module uses, connections, equipment models and
economics. The bundle compiles into an ordinary schema-1 profile, so everything
that runs a profile runs a bundle.

Two things a schema-1 profile cannot say, and a bundle can:

- **Equipment models.** A named set of parameter values for one module, with
  its maker, model and evidence.
- **Values per instance.** A module use may give an instance its own equipment
  model or its own values.

Values resolve in this order, the last winning: the module's default, the use's
equipment model, the use's ``params``, the instance's equipment model, the
instance's ``params``. Lowering splits a use into one use per distinct set of
resolved values, so a bundle with neither equipment nor overrides gives the very
profile, and hash, that the same content as one schema-1 file gives.

A bundle is data supplied by its owner and read offline: YAML is read with
``safe_load`` only, no path may leave the bundle directory, and the number and
size of files are bounded. Nothing in it is executed.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from agentic_datacenter.core.equipment import PREFIX, load_entry_file, registry_dir
from agentic_datacenter.core.profile import (
    ConnectionRule,
    ModuleUse,
    Param,
    Profile,
    ProfileError,
    parse_profile,
)
from agentic_datacenter.core.state import JsonValue

ENTRY = "datacenter.yaml"
MAX_FILES = 256
MAX_FILE_BYTES = 1024 * 1024
#: The keys an included file may hold.
PART_KEYS = ("key_sets", "tables", "modules", "connections", "equipment", "economics")


class FacilityError(ProfileError):
    """A facility bundle is unreadable, unsafe or invalid."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class EquipmentModel(_Model):
    """Values for one module, from one make and model of equipment."""

    module: str
    maker: Annotated[str, Field(min_length=1)]
    model: Annotated[str, Field(min_length=1)]
    evidence: Annotated[str, Field(min_length=1)]
    description: str = ""
    params: dict[str, Param] = Field(default_factory=dict)


class Override(_Model):
    """The equipment model or values of one instance."""

    equipment: str | None = None
    params: dict[str, Param] = Field(default_factory=dict)


class BundleUse(_Model):
    """A module use of a bundle: a schema-1 use with equipment and overrides."""

    id: str
    instances: Annotated[list[str], Field(min_length=1)] | None = None
    for_each: str | None = None
    instance: str | None = None
    stub: bool = False
    params: dict[str, Param] = Field(default_factory=dict)
    equipment: str | None = None
    overrides: dict[str, Override] = Field(default_factory=dict)

    def plain(self) -> dict[str, Any]:
        """The fields a schema-1 use has."""
        return self.model_dump(
            exclude={"equipment", "overrides"}, exclude_none=True, by_alias=True, mode="json"
        )


class Header(_Model):
    """``datacenter.yaml`` beyond the parts it may hold itself."""

    schema_version: Literal[2]
    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    site: str
    description: str = ""
    include: list[str] = Field(default_factory=list)


@dataclass(frozen=True)
class Facility:
    """A facility, compiled: the profile it lowers to and where it came from."""

    profile: Profile
    #: The SHA-256 of every file read, by its path relative to the bundle.
    files: dict[str, str]
    equipment: dict[str, EquipmentModel] = field(default_factory=dict)
    #: Resolved values counted by provenance, over every instance.
    values: dict[str, int] = field(default_factory=dict)
    description: str = ""

    def summary(self) -> dict[str, JsonValue]:
        """The ``facility`` block of a card (ADR 0033, decision 6)."""
        return {
            "name": self.profile.name,
            "site": self.profile.site,
            "description": self.description or self.profile.description,
            "profile_hash": self.profile.hash(),
            "files": dict(self.files),
            "equipment": {
                key: {
                    "module": m.module,
                    "maker": m.maker,
                    "model": m.model,
                    "evidence": m.evidence,
                }  # fmt: skip
                for key, m in sorted(self.equipment.items())
            },
            "values": dict(self.values),
        }


def _count(params: Mapping[str, Param], into: dict[str, int]) -> None:
    into.setdefault("sourced", 0)
    into.setdefault("assumed", 0)
    for p in params.values():
        into["assumed" if p.assumed else "sourced"] += 1


def _resolve_in(root: Path, pattern: str) -> list[Path]:
    """The files an include pattern names, each checked to lie inside *root*."""
    if not pattern.strip() or Path(pattern).parts in ((), (".",)):
        raise FacilityError(f"include {pattern!r}: names no file of the bundle")
    if Path(pattern).is_absolute() or ".." in Path(pattern).parts:
        raise FacilityError(f"include {pattern!r}: a path outside the bundle")
    try:
        matches = sorted(root.glob(pattern))
    except (ValueError, IndexError) as exc:
        raise FacilityError(f"include {pattern!r}: not a pattern: {exc}") from exc
    out = []
    for path in matches:
        real = path.resolve()
        if not real.is_relative_to(root):
            raise FacilityError(f"include {pattern!r}: {path.name} leads outside the bundle")
        if real.is_file():
            out.append(path)
    if not out:
        raise FacilityError(f"include {pattern!r}: names no file of the bundle")
    return out


def _read(root: Path, path: Path, files: dict[str, str]) -> Any:
    rel = path.relative_to(root).as_posix() if path.is_relative_to(root) else path.name
    if len(files) >= MAX_FILES:
        raise FacilityError(f"a bundle has at most {MAX_FILES} files")
    if path.stat().st_size > MAX_FILE_BYTES:
        raise FacilityError(f"{rel}: a file of a bundle is at most 1 MiB")
    raw = path.read_bytes()
    files[rel] = hashlib.sha256(raw).hexdigest()
    try:
        return yaml.safe_load(raw.decode("utf-8"))
    except (UnicodeDecodeError, yaml.YAMLError) as exc:
        raise FacilityError(f"{rel}: not YAML in UTF-8: {exc}") from exc


def _merge(parts: list[tuple[str, Mapping[str, Any]]]) -> dict[str, Any]:
    """Join lists in order and merge mappings, refusing a key defined twice."""
    merged: dict[str, Any] = {"modules": [], "connections": []}
    owner: dict[tuple[str, str], str] = {}
    for rel, part in parts:
        unknown = sorted(set(part) - set(PART_KEYS))
        if unknown:
            raise FacilityError(f"{rel}: a part of a bundle holds no {', '.join(unknown)}")
        for key in ("modules", "connections"):
            items = part.get(key) or []
            if not isinstance(items, list):
                raise FacilityError(f"{rel}: {key} is a list")
            merged[key].extend(items)
        for key in ("key_sets", "tables", "equipment", "economics"):
            items = part.get(key) or {}
            if not isinstance(items, Mapping):
                raise FacilityError(f"{rel}: {key} is a mapping")
            target = merged.setdefault(key, {})
            for name, value in items.items():
                if (key, name) in owner:
                    raise FacilityError(
                        f"{key}.{name} is defined in {owner[key, name]} and again in {rel}"
                    )
                owner[key, name] = rel
                target[name] = value
    return merged


def _names(use: BundleUse, key_sets: Mapping[str, list[str]]) -> list[str]:
    if use.instances is not None:
        return list(use.instances)
    if use.for_each is None or use.instance is None or use.for_each not in key_sets:
        raise FacilityError(f"module {use.id}: unknown key set {use.for_each!r}")
    return [
        Profile._fill(use.instance, {use.for_each: key})  # noqa: SLF001
        for key in key_sets[use.for_each]
    ]


def _from_model(key: str, model: EquipmentModel) -> dict[str, Param]:
    return {
        name: p if p.assumed else p.model_copy(update={"source": f"equipment {key}: {p.source}"})
        for name, p in model.params.items()
    }


def _lower(
    uses: list[BundleUse],
    key_sets: Mapping[str, list[str]],
    equipment: dict[str, EquipmentModel],
    values: dict[str, int],
    registry: Path,
    files: dict[str, str],
) -> tuple[list[dict[str, Any]], set[str]]:
    """Return the schema-1 uses of *uses*, and the equipment models they used."""
    out: list[dict[str, Any]] = []
    used: set[str] = set()

    def model(key: str | None, module_id: str) -> dict[str, Param]:
        if key is None:
            return {}
        if key.startswith(PREFIX) and key not in equipment:
            entry, entry_file = load_entry_file(key.removeprefix(PREFIX), registry)
            files[f"{PREFIX}{entry.id}"] = hashlib.sha256(entry_file.read_bytes()).hexdigest()
            equipment[key] = EquipmentModel(
                module=entry.module, maker=entry.maker, model=entry.model,
                evidence=entry.evidence, description=entry.variant, params=entry.params,
            )  # fmt: skip
        if key not in equipment:
            raise FacilityError(f"module {module_id}: no equipment model {key!r}")
        if equipment[key].module != module_id:
            raise FacilityError(
                f"equipment {key} is for {equipment[key].module}, and {module_id} names it"
            )
        used.add(key)
        return _from_model(key, equipment[key])

    for use in uses:
        names = _names(use, key_sets)
        stray = sorted(set(use.overrides) - set(names))
        if stray:
            raise FacilityError(f"module {use.id}: overrides for no instance of it: {stray}")
        base = {**model(use.equipment, use.id), **use.params}
        groups: list[tuple[dict[str, Param], list[str]]] = []
        for name in names:
            over = use.overrides.get(name, Override())
            resolved = {**base, **model(over.equipment, use.id), **over.params}
            _count(resolved, values)
            for params, members in groups:
                if params == resolved:
                    members.append(name)
                    break
            else:
                groups.append((resolved, [name]))
        if not groups or (len(groups) == 1 and groups[0][0] == use.params):
            out.append(use.plain())  # nothing to split: the use as it was written
            continue
        for params, members in groups:
            plain = {k: v for k, v in use.plain().items() if k not in ("for_each", "instance")}
            plain["instances"] = members
            plain["params"] = {k: p.model_dump(exclude_none=True) for k, p in params.items()}
            out.append(plain)
    return out, used


def _bundle(entry: Path, data: Mapping[str, Any], registry: Path) -> Facility:
    root = entry.parent.resolve()
    files: dict[str, str] = {}
    _read(root, entry, files)
    header_keys = {k: v for k, v in data.items() if k not in PART_KEYS}
    try:
        header = Header.model_validate(header_keys)
    except ValidationError as exc:
        raise FacilityError(f"{ENTRY}: {exc.errors()[0]['loc']}: {exc.errors()[0]['msg']}") from exc
    parts: list[tuple[str, Mapping[str, Any]]] = [
        (ENTRY, {k: v for k, v in data.items() if k in PART_KEYS})
    ]
    for pattern in header.include:
        for path in _resolve_in(root, pattern):
            rel = path.relative_to(root).as_posix()
            if rel in files:
                continue
            part = _read(root, path, files)
            if part is None:
                part = {}
            if not isinstance(part, Mapping):
                raise FacilityError(f"{rel}: a part of a bundle is a mapping")
            parts.append((rel, part))
    merged = _merge(parts)
    try:
        equipment = {
            key: EquipmentModel.model_validate(value)
            for key, value in merged.pop("equipment", {}).items()
        }
        uses = [BundleUse.model_validate(u) for u in merged["modules"]]
        [ConnectionRule.model_validate(c) for c in merged["connections"]]
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()
        )
        raise FacilityError(f"invalid bundle: {problems}") from exc
    key_sets: dict[str, list[str]] = merged.get("key_sets", {})
    values: dict[str, int] = {}
    forged = sorted(k for k in equipment if k.startswith(PREFIX))
    if forged:
        raise FacilityError(
            f"a bundle may not define {', '.join(forged)}: an entry named {PREFIX}<id> is read "
            "from the equipment registry, never from the bundle (ADR 0034)"
        )
    lowered, used = _lower(uses, key_sets, equipment, values, registry, files)
    profile_data: dict[str, Any] = {
        "schema_version": 1,
        "name": header.name,
        "description": header.description,
        "site": header.site,
        **{k: merged[k] for k in ("key_sets", "tables") if k in merged},
        "modules": lowered,
        "connections": merged["connections"],
        **({"economics": merged["economics"]} if "economics" in merged else {}),
    }
    try:
        profile = parse_profile(profile_data)
    except ProfileError as exc:
        raise FacilityError(str(exc)) from exc
    return Facility(
        profile=profile,
        files=files,
        equipment={k: equipment[k] for k in sorted(used)},
        values=values,
        description=header.description,
    )


def load_facility(path: Path, registry: Path | None = None) -> Facility:
    """Read a facility: a bundle directory, its ``datacenter.yaml``, or a schema-1 profile.

    A bundle may name entries of the equipment registry as ``registry:<id>``
    (ADR 0034); they are read from *registry*, by default ``equipment/`` of the
    working directory.

    Raises:
        FacilityError: If the bundle is unsafe, unreadable or invalid.
        ProfileError: If a schema-1 profile is invalid.
    """
    entry = path / ENTRY if path.is_dir() else path
    if not entry.is_file():
        raise FacilityError(f"{path}: no {ENTRY} and not a profile file")
    files: dict[str, str] = {}
    data = _read(entry.parent.resolve(), entry.resolve(), files)
    if not isinstance(data, Mapping):
        raise FacilityError(f"{entry}: a facility is a mapping")
    if data.get("schema_version") == 2:
        return _bundle(entry.resolve(), data, registry or registry_dir())
    profile = parse_profile(data)
    values: dict[str, int] = {}
    for use in profile.module_uses:
        for _ in range(len(use.instances) if use.instances else len(_names_v1(profile, use))):
            _count(use.params, values)
    return Facility(profile=profile, files={entry.name: files[entry.name]}, values=values)


def _names_v1(profile: Profile, use: ModuleUse) -> list[str]:
    assert use.for_each is not None
    return list(profile.key_sets[use.for_each])
