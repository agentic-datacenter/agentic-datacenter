"""The equipment registry: named equipment, its values and the rights to use them (ADR 0034).

An entry gives one make and model of equipment the values of one module, and
says where every value came from and what may be done with it. A facility
bundle names an entry as ``registry:<id>`` (ADR 0033).

Three tiers say how far an entry has been checked:

- ``factual``: values stated in a public source, taken as stated;
- ``calibrated``: values fitted to measurements, which the entry names;
- ``vendor_verified``: values the maker has checked, by a statement the entry names.

An entry is in the registry only when its source, its licence and the rights to
use it commercially and to redistribute it are recorded and allowed. That is the
registry's gate, held by ``tests/conformance/test_equipment_registry.py``.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agentic_datacenter.core.profile import Param, ProfileError

PREFIX = "registry:"
Allowed = Literal["allowed", "pending_review", "denied"]


class RegistryError(ProfileError):
    """An equipment registry entry is missing or invalid."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Provenance(_Model):
    """Where an entry's values came from."""

    source: str
    record: str
    description: str = ""
    lines: tuple[int, int] | None = None
    data_type: Literal["factual_specification", "measurement", "vendor_statement"]
    redistributes_source_document: Literal[False]
    derived_from: str = ""


class Simulation(_Model):
    """How the entry relates to the module that uses it."""

    model_origin: Literal["independently_developed", "vendor_supplied"]
    manufacturer_validated: bool
    calibration: Literal["uncalibrated", "calibrated"]


class Rights(_Model):
    """What may be done with the entry, and on what basis."""

    commercial_use: Allowed
    redistribution: Allowed
    basis: Annotated[str, Field(min_length=1)]
    reviewed: str


class Verification(_Model):
    """A maker's statement that it checked the values."""

    by: str
    date: str
    statement: str


class Entry(_Model):
    """One registry entry."""

    id: Annotated[str, Field(pattern=r"^[a-z0-9]+(\.[a-z0-9_]+)+$")]
    module: str
    maker: Annotated[str, Field(min_length=1)]
    model: Annotated[str, Field(min_length=1)]
    variant: str = ""
    tier: Literal["factual", "calibrated", "vendor_verified"]
    params: dict[str, Param]
    rated_conditions: dict[str, float | int | str] = Field(default_factory=dict)
    fit: str = ""
    provenance: Provenance
    simulation: Simulation
    rights: Rights
    verification: Verification | None = None

    @model_validator(mode="after")
    def _tier_is_earned(self) -> Entry:
        if self.simulation.manufacturer_validated != (self.tier == "vendor_verified"):
            raise ValueError("only a vendor_verified entry is manufacturer_validated")
        if (self.verification is not None) != (self.tier == "vendor_verified"):
            raise ValueError("a vendor_verified entry, and only one, names its verification")
        if self.tier == "calibrated" and self.simulation.calibration != "calibrated":
            raise ValueError("a calibrated entry says so in simulation.calibration")
        assumed = sorted(name for name, p in self.params.items() if p.assumed)
        if assumed:
            raise ValueError(f"a registry value has a source, never assumed: {assumed}")
        return self

    @property
    def evidence(self) -> str:
        """The evidence of the entry, as a facility card shows it."""
        return f"{self.tier}: {self.provenance.source} {self.provenance.record}"


def registry_dir(start: Path | None = None) -> Path:
    """Return the registry directory.

    In order: ``equipment/`` under *start*; the directory ``ADC_EQUIPMENT_REGISTRY``
    names; ``equipment/`` of the repository this package is installed from; and
    ``equipment/`` of the working directory.
    """
    if start is not None:
        return start / "equipment"
    named = os.environ.get("ADC_EQUIPMENT_REGISTRY")
    if named:
        return Path(named)
    for parent in Path(__file__).resolve().parents:
        if (parent / "equipment" / "sources.yaml").is_file() and (parent / "packages").is_dir():
            return parent / "equipment"
    return Path.cwd() / "equipment"


def load_entry(entry_id: str, root: Path | None = None) -> Entry:
    """Read registry entry *entry_id* from *root* (default: :func:`registry_dir`).

    Raises:
        RegistryError: If there is no such entry, it is invalid, or its rights
            are not allowed.
    """
    return load_entry_file(entry_id, root)[0]


def load_entry_file(entry_id: str, root: Path | None = None) -> tuple[Entry, Path]:
    """Read registry entry *entry_id*, and return it with the file it was read from."""
    base = root or registry_dir()
    matches = sorted(base.glob(f"*/{entry_id}.yaml"))
    if len(matches) != 1:
        raise RegistryError(f"no equipment registry entry {entry_id!r} in {base}")
    try:
        entry = Entry.model_validate(yaml.safe_load(matches[0].read_text(encoding="utf-8")))
    except (yaml.YAMLError, ValidationError) as exc:
        raise RegistryError(f"{matches[0]}: {exc}") from exc
    if entry.id != entry_id or matches[0].parent.name != entry.module:
        raise RegistryError(f"{matches[0]}: an entry's file is <module>/<id>.yaml")
    if (entry.rights.commercial_use, entry.rights.redistribution) != ("allowed", "allowed"):
        raise RegistryError(f"{entry_id}: its rights are not allowed, so it may not be used")
    return entry, matches[0]


def load_registry(root: Path | None = None) -> dict[str, Entry]:
    """Read every entry of the registry at *root*."""
    base = root or registry_dir()
    return {p.stem: load_entry(p.stem, base) for p in sorted(base.glob("*/*.yaml"))}


#: The licence every entry a maker contributes is under (decided by the owner on 2026-11-25).
VENDOR_LICENCE = "CC-BY-4.0"


def load_sources(root: Path | None = None) -> dict[str, dict[str, object]]:
    """Read ``sources.yaml`` of the registry at *root*."""
    base = root or registry_dir()
    data = yaml.safe_load((base / "sources.yaml").read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise RegistryError(f"{base / 'sources.yaml'}: a mapping of sources")
    return data


def problems(entry: Entry, sources: dict[str, dict[str, object]], repo: Path) -> list[str]:
    """Return why *entry* may not be in the registry, or nothing when it may (ADR 0034).

    The checks of the registry's gate that need more than the entry itself: its
    source is listed with a licence text, each value cites the source, and the
    rights fit the kind of source. A source of ``kind: vendor`` is a maker's own
    submission, under CC-BY-4.0; any other is an open source pinned by commit.
    """
    out: list[str] = []
    source = sources.get(entry.provenance.source)
    if source is None:
        return [f"source {entry.provenance.source!r} is not in sources.yaml"]
    licence_file = str(source.get("licence_file", ""))
    if not licence_file or not (repo / licence_file).is_file():
        out.append(f"source {entry.provenance.source}: no licence text at {licence_file!r}")
    if (entry.rights.commercial_use, entry.rights.redistribution) != ("allowed", "allowed"):
        out.append("commercial use and redistribution must both be allowed")
    vendor = source.get("kind") == "vendor"
    if vendor:
        if source.get("licence") != VENDOR_LICENCE:
            out.append(f"a maker's submission is under {VENDOR_LICENCE}")
        for key in ("submitted_by", "date", "attribution"):
            if not source.get(key):
                out.append(f"source {entry.provenance.source}: a maker's submission names {key}")
        if entry.simulation.model_origin != "vendor_supplied":
            out.append("a maker's entry has model_origin: vendor_supplied")
        if entry.provenance.data_type != "vendor_statement":
            out.append("a maker's entry has data_type: vendor_statement")
    else:
        commit = str(source.get("commit", ""))
        files = source.get("files")
        paths = list(files) if isinstance(files, dict) else []
        if len(commit) != 40:
            out.append(f"source {entry.provenance.source}: an open source is pinned by commit")
        for name, param in entry.params.items():
            text = param.source or ""
            if commit[:12] not in text or not any(path in text for path in paths):
                out.append(f"{name}: its source cites no pinned file and commit")
    for name, param in entry.params.items():
        if not (param.source or "").startswith(entry.provenance.source):
            out.append(f"{name}: its source does not start with {entry.provenance.source}")
    return out
