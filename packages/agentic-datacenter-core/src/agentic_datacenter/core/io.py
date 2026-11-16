"""Module I/O points.

Each plant module declares its points in ``points.yaml``. At run time they
live on an :class:`IOBoard`: the terminals of the module's controller. The
model writes measurements and feedback to the board, the controller reads them
and writes commands, and the model acts on the commands. A controller is given
the board and nothing else, exactly as a real controller sees only what is
wired to it (ADC-MOD-003).

A point's authority tier (SDD 7.1) is part of its declaration and cannot be
changed at run time.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agentic_datacenter.core.state import JsonValue

PointValue = bool | int | float | str
Kind = Literal["analog_in", "analog_setting", "binary_in", "binary_cmd", "enum_status", "counter"]


class PointError(ValueError):
    """A point declaration is invalid, or a point was used against its declaration."""


class PointDecl(BaseModel):
    """One point of a module."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: Annotated[str, Field(pattern=r"^[a-z][a-z0-9_]*$")]
    kind: Kind
    description: str
    tier: Literal["T0", "T1", "T2", "T3"]
    default: bool | int | float | str
    unit: str = ""
    range: tuple[float, float] | None = None
    step: float | None = None
    values: tuple[str, ...] | None = None
    source: str | None = None
    assumed: bool | None = None

    @model_validator(mode="after")
    def _consistent(self) -> PointDecl:
        if bool(self.source and self.source.strip()) == bool(self.assumed):
            raise ValueError(f"{self.name}: give exactly one of `source` or `assumed: true`")
        if self.kind == "enum_status" and not self.values:
            raise ValueError(f"{self.name}: an enum point needs `values`")
        problem = self.problem_with(self.default)
        if problem:
            raise ValueError(f"{self.name}: default {problem}")
        return self

    def problem_with(self, value: object) -> str | None:
        """Return why *value* does not fit this point, or None if it fits."""
        if self.kind.startswith("binary"):
            return None if isinstance(value, bool) else "must be a bool"
        if self.kind == "enum_status":
            return None if value in (self.values or ()) else f"must be one of {self.values}"
        if self.kind == "counter":
            ok = isinstance(value, int) and not isinstance(value, bool) and value >= 0
            return None if ok else "must be a non-negative int"
        if isinstance(value, bool) or not isinstance(value, int | float):
            return "must be a number"
        if not math.isfinite(value):
            return "must be finite"
        if self.range is not None and not self.range[0] <= value <= self.range[1]:
            return f"must be within {list(self.range)}"
        if self.step is not None and abs(value / self.step - round(value / self.step)) > 1e-9:
            return f"must be a multiple of {self.step}"
        return None


def parse_points(data: object) -> tuple[PointDecl, ...]:
    """Validate a list of point declarations.

    Raises:
        PointError: If a declaration is invalid or a name is used twice.
    """
    if not isinstance(data, Sequence) or isinstance(data, str):
        raise PointError("points must be a list")
    try:
        points = tuple(PointDecl.model_validate(item) for item in data)
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']} (got {e['input']!r})"
            for e in exc.errors()
        )
        raise PointError(f"invalid point: {problems}") from exc
    names = [p.name for p in points]
    repeated = sorted({n for n in names if names.count(n) > 1})
    if repeated:
        raise PointError(f"point name(s) used more than once: {', '.join(repeated)}")
    return points


def load_points(path: Path) -> tuple[PointDecl, ...]:
    """Read and validate the ``points.yaml`` at *path*."""
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise PointError(f"cannot read points {path}: {exc}") from exc
    try:
        return parse_points(data)
    except PointError as exc:
        raise PointError(f"{path}: {exc}") from exc


def _fast_check(decl: PointDecl) -> Callable[[object], bool]:
    """Return a cheap test that accepts every value the declaration allows.

    It may refuse a value that is in fact allowed (an int written to an analog
    point, a setting with a step); the board then falls back to the full check,
    which decides and words the error. It never accepts a value that is not
    allowed.
    """
    if decl.kind.startswith("binary"):
        return lambda value: value is True or value is False
    if decl.kind == "enum_status":
        allowed = frozenset(decl.values or ())
        return lambda value: type(value) is str and value in allowed
    if decl.kind == "counter" or decl.step is not None or decl.range is None:
        return lambda value: False
    low, high = decl.range
    return lambda value: type(value) is float and low <= value <= high


class IOBoard:
    """The current value of every declared point of one module instance."""

    def __init__(self, points: Sequence[PointDecl]) -> None:
        """Create a board with every point at its default."""
        self._decl = {p.name: p for p in points}
        self._value: dict[str, PointValue] = {p.name: p.default for p in points}
        self._fast = {p.name: _fast_check(p) for p in points}

    def __getitem__(self, name: str) -> PointValue:
        """Return the value of point *name*."""
        try:
            return self._value[name]
        except KeyError:
            raise PointError(f"no such point: {name!r}") from None

    def __setitem__(self, name: str, value: PointValue) -> None:
        """Set point *name*, refusing a value its declaration does not allow."""
        try:
            if self._fast[name](value):
                self._value[name] = value
                return
        except KeyError:
            raise PointError(f"no such point: {name!r}") from None
        problem = self._decl[name].problem_with(value)
        if problem:
            raise PointError(f"{name}: value {value!r} {problem}")
        self._value[name] = value

    def __iter__(self) -> Iterator[str]:
        """Iterate over the point names."""
        return iter(self._decl)

    def declaration(self, name: str) -> PointDecl:
        """Return the declaration of point *name*."""
        try:
            return self._decl[name]
        except KeyError:
            raise PointError(f"no such point: {name!r}") from None

    def number(self, name: str) -> float:
        """Return a numeric point as a float."""
        value = self[name]
        if isinstance(value, bool) or not isinstance(value, int | float):
            raise PointError(f"{name} is not numeric")
        return float(value)

    def flag(self, name: str) -> bool:
        """Return a binary point."""
        value = self[name]
        if not isinstance(value, bool):
            raise PointError(f"{name} is not binary")
        return value

    def snapshot(self) -> JsonValue:
        """Return every point value."""
        return dict(self._value)

    def restore(self, state: JsonValue) -> None:
        """Put back values returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping) or state.keys() != self._value.keys():
            raise PointError("point snapshot does not match this board")
        for name, value in state.items():
            self[name] = value  # type: ignore[assignment]
