"""The dataset manifest: what a measured series is, where it came from, and its hashes.

A manifest is ``dataset_manifest.json`` beside the files it describes. It
records the source, version and licence as the source states them, whether the
data may be redistributed, the period, the step, the units of each column, the
gap tolerance, and the SHA-256 of every file. Agentic Datacenter refuses a series whose
files do not match their hashes.
"""

from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

MANIFEST_NAME = "dataset_manifest.json"
SCHEMA_VERSION = 1

#: Columns Agentic Datacenter reads, the quantity each holds and the units it converts.
COLUMNS: dict[str, tuple[str, tuple[str, ...]]] = {
    "dry_bulb": ("outdoor dry-bulb temperature", ("degC", "K", "degF")),
    "dew_point": ("outdoor dew-point temperature", ("degC", "K", "degF")),
    "rel_humidity": ("outdoor relative humidity", ("%",)),
}

_UTC = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
UtcText = Annotated[str, Field(pattern=_UTC.pattern)]
Sha256 = Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Period(_Model):
    """First and last timestamp of the series, in UTC."""

    start_utc: UtcText
    end_utc: UtcText


class Column(_Model):
    """One value column of the series."""

    unit: str
    description: str = ""


class FileEntry(_Model):
    """One file of the dataset and its SHA-256."""

    path: Annotated[str, Field(min_length=1)]
    sha256: Sha256


class DatasetManifest(_Model):
    """The contents of ``dataset_manifest.json``."""

    schema_version: Literal[1]
    dataset_id: Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_.-]*$")]
    title: str
    source: Annotated[str, Field(min_length=1)]
    version: Annotated[str, Field(min_length=1)]
    doi: str | None = None
    licence: Annotated[str, Field(min_length=1)]
    redistribution: Literal["not_cleared", "cleared"]
    quality_status: Annotated[str, Field(min_length=1)]
    period: Period
    step_s: Annotated[int, Field(gt=0)]
    gap_tolerance_s: Annotated[int, Field(ge=0)]
    columns: Annotated[dict[str, Column], Field(min_length=1)]
    series_file: Annotated[str, Field(min_length=1)]
    files: Annotated[list[FileEntry], Field(min_length=1)]
    derivation: str = ""
    notes: str = ""
