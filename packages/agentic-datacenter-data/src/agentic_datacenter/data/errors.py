"""Errors raised by the measured input layer.

Each names what is wrong and where, so a run that cannot use its data stops
with a message the owner of the dataset can act on.
"""

from __future__ import annotations


class MeasuredSeriesError(ValueError):
    """A measured series cannot be used as it is."""


class ManifestInvalid(MeasuredSeriesError):
    """The dataset manifest or the series file does not follow the format."""


class DatasetFileMissing(MeasuredSeriesError):
    """The manifest or a file it lists does not exist."""


class HashMismatch(MeasuredSeriesError):
    """A file differs from the SHA-256 recorded in the manifest."""


class UnitNotUnderstood(MeasuredSeriesError):
    """A column is declared in a unit Agentic Datacenter does not convert."""


class OutsideSeries(MeasuredSeriesError):
    """A value was asked for at a time the series does not cover; nothing is extrapolated."""


class GapTooLong(MeasuredSeriesError):
    """Missing values span more than the gap tolerance declared in the manifest."""
