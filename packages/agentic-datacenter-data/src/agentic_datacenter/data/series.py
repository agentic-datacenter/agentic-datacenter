"""A measured series in Agentic-Datacenter's CSV format, read against its manifest.

The format is Agentic-Datacenter's own, independent of any source:

- UTF-8 CSV with a header row. The first column is ``time_utc``; the others are
  columns Agentic-Datacenter knows
  (:data:`agentic_datacenter.data.manifest.COLUMNS`), each declared with its
  unit in the manifest.
- ``time_utc`` is ISO 8601 in UTC with the ``Z`` designator, to the second
  (``2020-07-01T13:00:00Z``). Rows are strictly increasing and lie on the step
  declared in the manifest. A missing row and an empty cell both mean "no
  measured value".

Values are linearly interpolated between the two nearest measured samples.
Nothing is extrapolated before the first or after the last sample. Missing
samples are bridged only when the missing stretch is no longer than the
``gap_tolerance_s`` the manifest declares; otherwise reading inside it fails.
Time is an integer count of milliseconds since 1970-01-01T00:00:00Z, so the same
file always gives the same values.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
from bisect import bisect_left
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

from pydantic import ValidationError

from agentic_datacenter.data.errors import (
    DatasetFileMissing,
    GapTooLong,
    HashMismatch,
    ManifestInvalid,
    OutsideSeries,
    UnitNotUnderstood,
)
from agentic_datacenter.data.manifest import _UTC, COLUMNS, MANIFEST_NAME, DatasetManifest

TIME_COLUMN = "time_utc"
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_TO_CELSIUS: dict[str, Callable[[float], float]] = {
    "degC": lambda v: v,
    "K": lambda v: v - 273.15,
    "degF": lambda v: (v - 32.0) * 5.0 / 9.0,
}
_CONVERT: dict[str, Callable[[float], float]] = {**_TO_CELSIUS, "%": lambda v: v}


def parse_utc_ms(text: str) -> int:
    """Return the UTC timestamp *text* (``YYYY-MM-DDThh:mm:ssZ``) as milliseconds since 1970.

    Raises:
        ValueError: If *text* is not in that form; a timestamp without the UTC
            designator is refused rather than guessed.
    """
    if not _UTC.match(text):
        raise ValueError(f"{text!r} is not a UTC timestamp of the form YYYY-MM-DDThh:mm:ssZ")
    moment = datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    return (moment - _EPOCH) // timedelta(milliseconds=1)


def format_utc(ms: int) -> str:
    """Return *ms* since 1970 as ``YYYY-MM-DDThh:mm:ssZ`` (milliseconds are dropped)."""
    return (_EPOCH + timedelta(milliseconds=ms)).strftime("%Y-%m-%dT%H:%M:%SZ")


def _rows(text: str, step_s: int, name: str) -> tuple[list[str], list[int], list[list[str]]]:
    """Return header, times and value cells of a series; check timestamps and step."""
    reader = csv.reader(text.splitlines())
    try:
        header = next(reader)
    except StopIteration:
        raise ManifestInvalid(f"{name} is empty") from None
    if not header or header[0] != TIME_COLUMN:
        raise ManifestInvalid(f"{name}: the first column must be {TIME_COLUMN!r}")
    times: list[int] = []
    cells: list[list[str]] = []
    step_ms = step_s * 1000
    for line, row in enumerate(reader, start=2):
        if not row:
            continue
        if len(row) != len(header):
            raise ManifestInvalid(f"{name} line {line}: {len(row)} cells, header has {len(header)}")
        try:
            t = parse_utc_ms(row[0])
        except ValueError as exc:
            raise ManifestInvalid(f"{name} line {line}: {exc}") from None
        if times and (t <= times[-1] or (t - times[-1]) % step_ms):
            raise ManifestInvalid(
                f"{name} line {line}: {row[0]} does not follow the previous row on the "
                f"step of {step_s} s"
            )
        times.append(t)
        cells.append(row[1:])
    if not times:
        raise ManifestInvalid(f"{name} has no rows")
    return header, times, cells


def _inside(directory: Path, relative: str) -> Path:
    path = (directory / relative).resolve()
    if Path(relative).is_absolute() or not path.is_relative_to(directory.resolve()):
        raise ManifestInvalid(f"{relative!r} must be a relative path inside the dataset directory")
    return path


def _check_columns(manifest: DatasetManifest) -> None:
    for name, column in manifest.columns.items():
        if name not in COLUMNS:
            known = ", ".join(sorted(COLUMNS))
            raise ManifestInvalid(
                f"column {name!r} is not one Agentic-Datacenter reads; known: {known}"
            )
        accepted = COLUMNS[name][1]
        if column.unit not in accepted:
            raise UnitNotUnderstood(
                f"column {name!r} is declared in {column.unit!r}, which Agentic-Datacenter "
                f"does not convert; use one of {', '.join(accepted)}"
            )


@dataclass(frozen=True)
class MeasuredSeries:
    """A verified measured series, with values in Agentic-Datacenter units (°C, %).

    Attributes:
        manifest: The validated manifest.
        manifest_sha256: SHA-256 of the manifest file as read.
        file_sha256: SHA-256 of every file the manifest lists, by its path.
        columns: The value columns, in file order.
        start_ms: First timestamp, milliseconds since 1970 UTC.
        end_ms: Last timestamp, milliseconds since 1970 UTC.
    """

    manifest: DatasetManifest
    manifest_sha256: str
    file_sha256: Mapping[str, str]
    columns: tuple[str, ...]
    start_ms: int
    end_ms: int
    _times: Mapping[str, tuple[int, ...]] = field(repr=False)
    _values: Mapping[str, tuple[float, ...]] = field(repr=False)

    def value_at(self, column: str, t_ms: int) -> float:
        """Return *column* at *t_ms* (ms since 1970 UTC), interpolated linearly.

        Raises:
            KeyError: If the series has no such column.
            OutsideSeries: If *t_ms* is outside the series, or beyond its last
                measured value of *column* (nothing is extrapolated).
            GapTooLong: If *t_ms* falls in a stretch of missing values longer
                than the declared gap tolerance.
        """
        if t_ms < self.start_ms:
            raise OutsideSeries(
                f"{format_utc(t_ms)} is before the series starts at {format_utc(self.start_ms)}"
            )
        if t_ms > self.end_ms:
            raise OutsideSeries(
                f"{format_utc(t_ms)} is after the series ends at {format_utc(self.end_ms)}"
            )
        times, values = self._times[column], self._values[column]
        i = bisect_left(times, t_ms)
        if i < len(times) and times[i] == t_ms:
            return values[i]
        if i == 0:
            raise OutsideSeries(
                f"no measured value of {column} at or before {format_utc(t_ms)}; "
                "the series is not extrapolated"
            )
        if i == len(times):
            raise OutsideSeries(
                f"no measured value of {column} after {format_utc(times[-1])}; "
                "the series is not extrapolated"
            )
        t0, t1 = times[i - 1], times[i]
        missing_ms = t1 - t0 - self.manifest.step_s * 1000
        if missing_ms > self.manifest.gap_tolerance_s * 1000:
            raise GapTooLong(
                f"{column}: no measured value between {format_utc(t0)} and {format_utc(t1)}, "
                f"a gap of {missing_ms // 1000} s, beyond the tolerance of "
                f"{self.manifest.gap_tolerance_s} s declared for {self.manifest.dataset_id}"
            )
        v0, v1 = values[i - 1], values[i]
        return v0 + (v1 - v0) * ((t_ms - t0) / (t1 - t0))

    def gaps(self, column: str, from_ms: int, to_ms: int) -> list[tuple[int, int]]:
        """Return the bridged gaps of *column* that overlap ``[from_ms, to_ms]``.

        A gap is given by the measured samples on either side of it.
        """
        times, step_ms = self._times[column], self.manifest.step_s * 1000
        return [
            (t0, t1)
            for t0, t1 in zip(times, times[1:], strict=False)
            if t1 - t0 > step_ms and t1 > from_ms and t0 < to_ms
        ]

    def provenance(self) -> dict[str, object]:
        """Return what an evidence bundle records about this series."""
        m, step_ms = self.manifest, self.manifest.step_s * 1000
        bridged: dict[str, dict[str, int]] = {}
        for column in self.columns:
            gaps = self.gaps(column, self.start_ms, self.end_ms)
            longest = max((t1 - t0 - step_ms for t0, t1 in gaps), default=0)
            bridged[column] = {"count": len(gaps), "longest_s": longest // 1000}
        return {
            "dataset_id": m.dataset_id,
            "title": m.title,
            "source": m.source,
            "version": m.version,
            "doi": m.doi,
            "licence": m.licence,
            "redistribution": m.redistribution,
            "quality_status": m.quality_status,
            "period": m.period.model_dump(),
            "step_s": m.step_s,
            "gap_tolerance_s": m.gap_tolerance_s,
            "units": {name: m.columns[name].unit for name in self.columns},
            "manifest_sha256": self.manifest_sha256,
            "files": dict(self.file_sha256),
            "bridged_gaps": bridged,
        }


def _read(path: Path, what: str) -> bytes:
    try:
        return path.read_bytes()
    except FileNotFoundError:
        raise DatasetFileMissing(f"{what} {path} does not exist") from None
    except OSError as exc:
        raise DatasetFileMissing(f"{what} {path} cannot be read: {exc}") from None


def _validate(data: object, where: str) -> DatasetManifest:
    try:
        return DatasetManifest.model_validate(data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'manifest'}: {e['msg']}" for e in exc.errors()
        )
        raise ManifestInvalid(f"{where}: {problems}") from None


def load_series(manifest_path: Path) -> MeasuredSeries:
    """Read the dataset at *manifest_path*, verify every file's hash, and return its series.

    Raises:
        DatasetFileMissing: If the manifest or a file it lists does not exist.
        ManifestInvalid: If the manifest or the series does not follow the format.
        UnitNotUnderstood: If a column is declared in a unit Agentic-Datacenter does not convert.
        HashMismatch: If a file differs from its recorded SHA-256.
    """
    raw = _read(manifest_path, "dataset manifest")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ManifestInvalid(f"{manifest_path} is not JSON: {exc}") from None
    manifest = _validate(data, str(manifest_path))
    _check_columns(manifest)
    directory = manifest_path.parent
    _inside(directory, manifest.series_file)
    listed = {entry.path: entry.sha256 for entry in manifest.files}
    if manifest.series_file not in listed:
        raise ManifestInvalid(f"{manifest.series_file!r} is not listed in `files` with a hash")
    contents: dict[str, bytes] = {}
    for name, expected in listed.items():
        body = _read(_inside(directory, name), f"{name}, listed in {manifest_path.name},")
        actual = hashlib.sha256(body).hexdigest()
        if actual != expected:
            raise HashMismatch(
                f"{name}: SHA-256 is {actual}, but {manifest_path.name} records {expected}"
            )
        contents[name] = body
    try:
        text = contents[manifest.series_file].decode("utf-8")
    except UnicodeDecodeError:
        raise ManifestInvalid(f"{manifest.series_file} is not UTF-8") from None
    header, times, cells = _rows(text, manifest.step_s, manifest.series_file)
    value_columns = header[1:]
    if sorted(value_columns) != sorted(manifest.columns) or len(set(value_columns)) != len(
        value_columns
    ):
        raise ManifestInvalid(
            f"{manifest.series_file} has columns {value_columns}, the manifest declares "
            f"{sorted(manifest.columns)}"
        )
    found = (format_utc(times[0]), format_utc(times[-1]))
    declared = (manifest.period.start_utc, manifest.period.end_utc)
    if found != declared:
        raise ManifestInvalid(f"period in the manifest {declared} does not match the file {found}")
    per_time: dict[str, list[int]] = {c: [] for c in value_columns}
    per_value: dict[str, list[float]] = {c: [] for c in value_columns}
    for t, row in zip(times, cells, strict=True):
        for column, cell in zip(value_columns, row, strict=True):
            if cell.strip() == "":
                continue
            try:
                value = float(cell)
            except ValueError:
                raise ManifestInvalid(
                    f"{manifest.series_file} at {format_utc(t)}: {column} is {cell!r}"
                ) from None
            if not math.isfinite(value):
                raise ManifestInvalid(
                    f"{manifest.series_file} at {format_utc(t)}: {column} is not finite"
                )
            per_time[column].append(t)
            per_value[column].append(_CONVERT[manifest.columns[column].unit](value))
    return MeasuredSeries(
        manifest=manifest,
        manifest_sha256=hashlib.sha256(raw).hexdigest(),
        file_sha256={name: hashlib.sha256(body).hexdigest() for name, body in contents.items()},
        columns=tuple(value_columns),
        start_ms=times[0],
        end_ms=times[-1],
        _times={c: tuple(v) for c, v in per_time.items()},
        _values={c: tuple(v) for c, v in per_value.items()},
    )


def write_manifest(
    series_path: Path,
    *,
    dataset_id: str,
    title: str,
    source: str,
    version: str,
    licence: str,
    redistribution: str,
    quality_status: str,
    units: Mapping[str, str],
    gap_tolerance_s: int,
    step_s: int = 3600,
    doi: str | None = None,
    derivation: str = "",
    notes: str = "",
    extra_files: Sequence[Path] = (),
) -> Path:
    """Write ``dataset_manifest.json`` beside *series_path* and return its path.

    The period and the hashes are taken from the files, so they cannot be
    mistyped. *licence* is the licence as the source states it, not a reading of
    it. The written manifest is read back with :func:`load_series`.

    Raises:
        ManifestInvalid: If the series does not follow the format, or a field is invalid.
        UnitNotUnderstood: If a unit is not one Agentic-Datacenter converts.
    """
    directory = series_path.parent
    text = _read(series_path, "series").decode("utf-8")
    _, times, _ = _rows(text, step_s, series_path.name)
    files = [series_path, *extra_files]
    data = {
        "schema_version": 1,
        "dataset_id": dataset_id,
        "title": title,
        "source": source,
        "version": version,
        "doi": doi,
        "licence": licence,
        "redistribution": redistribution,
        "quality_status": quality_status,
        "period": {"start_utc": format_utc(times[0]), "end_utc": format_utc(times[-1])},
        "step_s": step_s,
        "gap_tolerance_s": gap_tolerance_s,
        "columns": {name: {"unit": unit} for name, unit in units.items()},
        "series_file": series_path.name,
        "files": [
            {
                "path": str(path.resolve().relative_to(directory.resolve())),
                "sha256": hashlib.sha256(_read(path, "file")).hexdigest(),
            }
            for path in files
        ],
        "derivation": derivation,
        "notes": notes,
    }
    manifest = _validate(data, MANIFEST_NAME)
    out = directory / MANIFEST_NAME
    out.write_text(json.dumps(manifest.model_dump(mode="json"), indent=2) + "\n", "utf-8")
    load_series(out)
    return out
