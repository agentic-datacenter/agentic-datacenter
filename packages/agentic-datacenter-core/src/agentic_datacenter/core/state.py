"""Canonical state encoding, the state hash and the registry of stateful parts.

Everything that must be reproducible is expressed in the JSON domain and
encoded one way only. The encoding is exact: a float is written as its
hexadecimal form, so two states hash alike only if they are bit-identical
(ADC-KRN-001).
"""

from __future__ import annotations

import copy
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Protocol

type JsonValue = None | bool | int | float | str | Sequence["JsonValue"] | Mapping[str, "JsonValue"]


def _check(value: object) -> None:
    """Refuse anything JSON would accept but that could make two states encode alike."""
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise TypeError(f"state keys must be str, got {type(key).__name__}")
            _check(item)
    elif isinstance(value, list | tuple):
        for item in value:
            _check(item)
    elif not (value is None or isinstance(value, bool | int | float | str)):
        raise TypeError(f"not a JSON-domain value: {type(value).__name__}")


def _dumps(value: JsonValue) -> bytes:
    try:
        text = json.dumps(
            value, sort_keys=True, allow_nan=False, separators=(",", ":"), ensure_ascii=False
        )
    except ValueError as exc:
        raise ValueError(f"state values must be finite: {exc}") from exc
    return text.encode("utf-8")


def canonical_bytes(value: JsonValue) -> bytes:
    """Encode *value* deterministically and exactly.

    The encoding is compact JSON with sorted keys. Python writes a float as the
    shortest text that reads back to the same bits, so two floats encode alike
    only if they are identical; ``1``, ``1.0`` and ``true`` stay distinct; a
    tuple encodes as a list.

    Raises:
        TypeError: If a value or a mapping key is outside the JSON domain.
        ValueError: If a float is NaN or infinite.
    """
    _check(value)
    return _dumps(value)


def state_hash(value: JsonValue) -> str:
    """Return the SHA-256 hex digest of the canonical encoding of *value*."""
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def _quantize(value: JsonValue, digits: int) -> JsonValue:
    if isinstance(value, bool) or value is None or isinstance(value, int | str):
        return value
    if isinstance(value, float):
        return float(f"{value:.{digits - 1}e}")
    if isinstance(value, Mapping):
        return {key: _quantize(item, digits) for key, item in value.items()}
    return [_quantize(item, digits) for item in value]


def quantized_hash(value: JsonValue, digits: int = 9) -> str:
    """Return the hash of *value* with floats rounded to *digits* significant digits.

    For comparing runs on different CPU architectures, where the platform math
    library may differ in the last bits (ADC-CI-004). Integers, booleans and
    strings stay exact. A value that sits on a rounding boundary can still
    differ; the comparison job reports such a case instead of hiding it.
    """
    return state_hash(_quantize(value, digits))


#: How often the registry repeats the full domain check on a part it encodes.
RECHECK_EVERY = 1000


class Snapshottable(Protocol):
    """A part whose complete state can be saved and put back."""

    def snapshot(self) -> JsonValue:
        """Return the complete state as a JSON-domain value."""
        ...

    def restore(self, state: JsonValue) -> None:
        """Replace the state with one returned earlier by :meth:`snapshot`."""
        ...


class StateRegistry:
    """The named parts that together make up the simulator state.

    The state hash is taken over the digests of the parts: SHA-256 of the
    sorted (name, digest) pairs, where a part's digest is the hash of its
    canonical encoding. A part registered as *tracked* keeps its digest until
    :meth:`touch` says it changed, so a hash costs time in proportion to what
    changed, not to the size of the plant. Tracking is an optimization only:
    the result is the hash an untracked registry gives for the same state.
    """

    def __init__(self) -> None:
        """Create an empty registry."""
        self._parts: dict[str, Snapshottable] = {}
        self._tracked: set[str] = set()
        self._digests: dict[str, bytes] = {}
        self._encoded: dict[str, int] = {}

    def register(self, name: str, part: Snapshottable, *, tracked: bool = False) -> None:
        """Add *part* under *name*.

        Args:
            name: Unique name of the part.
            part: The part.
            tracked: The owner promises to call :meth:`touch` whenever the
                part's state may have changed.

        Raises:
            ValueError: If the name is already taken.
        """
        if name in self._parts:
            raise ValueError(f"state part {name!r} is already registered")
        self._parts[name] = part
        if tracked:
            self._tracked.add(name)

    def touch(self, name: str) -> None:
        """Say that the tracked part *name* may have changed.

        Raises:
            KeyError: If there is no such part.
        """
        if name not in self._parts:
            raise KeyError(name)
        self._digests.pop(name, None)

    def snapshot(self) -> dict[str, JsonValue]:
        """Return the state of every part, independent of later changes."""
        return {name: copy.deepcopy(part.snapshot()) for name, part in self._parts.items()}

    def restore(self, state: Mapping[str, JsonValue]) -> None:
        """Put back a snapshot taken from a registry with the same parts.

        Raises:
            ValueError: If the snapshot lacks a registered part or names an
                unknown one. Nothing is restored in that case.
        """
        missing = sorted(self._parts.keys() - state.keys())
        unknown = sorted(state.keys() - self._parts.keys())
        if missing:
            raise ValueError(f"snapshot is missing part(s) {', '.join(map(repr, missing))}")
        if unknown:
            raise ValueError(f"snapshot has unknown part(s) {', '.join(map(repr, unknown))}")
        for name, part in self._parts.items():
            part.restore(copy.deepcopy(state[name]))
        self._digests.clear()

    def _encode(self, name: str) -> bytes:
        """Encode one part, with the full domain check on a sample of the calls.

        The check walks the snapshot in Python and costs several times the
        encoding itself, so it runs the first time a part is encoded and then
        on every :data:`RECHECK_EVERY`-th encoding of it. The encoder refuses
        non-finite floats and foreign types on every call; what the sampled
        check adds is refusing a mapping key that is not a string.
        """
        snapshot = self._parts[name].snapshot()
        seen = self._encoded.get(name, 0)
        if seen % RECHECK_EVERY == 0:
            _check(snapshot)
        self._encoded[name] = seen + 1
        return _dumps(snapshot)

    def stale_parts(self) -> list[str]:
        """Return the tracked parts whose kept digest no longer matches their state.

        Always empty when every owner of a tracked part calls :meth:`touch` as
        promised. A name here means a part changed without saying so, and that
        the state hash did not see the change. For tests.
        """
        stale = []
        for name, kept in sorted(self._digests.items()):
            fresh = hashlib.sha256(_dumps(self._parts[name].snapshot())).digest()
            if fresh != kept:
                stale.append(name)
        return stale

    def hash(self) -> str:
        """Return the state hash over every registered part."""
        outer = hashlib.sha256()
        for name in sorted(self._parts):
            digest = self._digests.get(name) if name in self._tracked else None
            if digest is None:
                digest = hashlib.sha256(self._encode(name)).digest()
                if name in self._tracked:
                    self._digests[name] = digest
            raw = name.encode("utf-8")
            outer.update(b"%d:" % len(raw) + raw + digest)
        return outer.hexdigest()
