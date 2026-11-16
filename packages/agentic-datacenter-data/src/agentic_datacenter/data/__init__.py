"""Measured input series (ADR 0018).

A measured series is a fixed-step time series in Agentic-Datacenter's CSV format with a
``dataset_manifest.json`` beside it. :func:`load_series` verifies the hash of
every file and returns a :class:`MeasuredSeries` whose values can be read at
any instant inside it, by linear interpolation, without extrapolation and
without silently filling gaps. No dataset ships with Agentic-Datacenter.
"""

from agentic_datacenter.data.errors import (
    DatasetFileMissing,
    GapTooLong,
    HashMismatch,
    ManifestInvalid,
    MeasuredSeriesError,
    OutsideSeries,
    UnitNotUnderstood,
)
from agentic_datacenter.data.manifest import COLUMNS, MANIFEST_NAME, DatasetManifest
from agentic_datacenter.data.series import (
    TIME_COLUMN,
    MeasuredSeries,
    format_utc,
    load_series,
    parse_utc_ms,
    write_manifest,
)

__all__ = [
    "COLUMNS",
    "MANIFEST_NAME",
    "TIME_COLUMN",
    "DatasetFileMissing",
    "DatasetManifest",
    "GapTooLong",
    "HashMismatch",
    "ManifestInvalid",
    "MeasuredSeries",
    "MeasuredSeriesError",
    "OutsideSeries",
    "UnitNotUnderstood",
    "format_utc",
    "load_series",
    "parse_utc_ms",
    "write_manifest",
]
