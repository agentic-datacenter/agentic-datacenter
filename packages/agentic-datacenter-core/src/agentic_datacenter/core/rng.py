"""Seeded random streams.

Every source of randomness in a run is a named stream derived from the run
seed. Streams are independent: what one consumer draws never changes what
another sees, and the order in which streams are first used does not matter.

A stream is a SplitMix64 generator. Its whole state is one 64-bit counter, so
it is cheap to include in the state hash at every step; the standard-library
generator carries 625 words of state per stream, which is not.
"""

from __future__ import annotations

import hashlib
from random import Random
from typing import Any

from agentic_datacenter.core.state import JsonValue

_MASK64 = (1 << 64) - 1
_GAMMA = 0x9E3779B97F4A7C15
_TO_UNIT = 2.0**-53


def splitmix64_next(state: int) -> tuple[int, int]:
    """Advance a SplitMix64 state once.

    Returns:
        The new state and the 64-bit output drawn from it.
    """
    state = (state + _GAMMA) & _MASK64
    z = state
    z = ((z ^ (z >> 30)) * 0xBF58476D1CE4E5B9) & _MASK64
    z = ((z ^ (z >> 27)) * 0x94D049BB133111EB) & _MASK64
    return state, z ^ (z >> 31)


def _derive(seed: int, name: str) -> int:
    digest = hashlib.sha256(f"agentic-datacenter-stream:{seed}:{name}".encode()).digest()
    return int.from_bytes(digest[:8], "big")


class Stream(Random):
    """One random stream, with every distribution of :class:`random.Random`."""

    _state: int
    gauss_next: float | None

    def seed(self, a: Any = None, version: int = 2) -> None:
        """Start the stream from the 64-bit value *a*.

        Raises:
            TypeError: If *a* is not an int. A stream is never seeded from the
                operating system (ADC-KRN-003).
        """
        if not isinstance(a, int) or isinstance(a, bool):
            raise TypeError("a stream needs an explicit integer seed")
        self._state = a & _MASK64
        self.gauss_next = None

    def random(self) -> float:
        """Return the next float in [0.0, 1.0)."""
        self._state, value = splitmix64_next(self._state)
        return (value >> 11) * _TO_UNIT

    def getrandbits(self, k: int, /) -> int:
        """Return a non-negative int with *k* random bits."""
        if k < 0:
            raise ValueError("number of bits must be non-negative")
        result, have = 0, 0
        while have < k:
            self._state, value = splitmix64_next(self._state)
            result |= value << have
            have += 64
        return result & ((1 << k) - 1)

    def getstate(self) -> tuple[Any, ...]:
        """Return the counter and the cached half of a gauss pair."""
        return (self._state, self.gauss_next)

    def setstate(self, state: tuple[Any, ...]) -> None:
        """Put back a state returned by :meth:`getstate`."""
        counter, gauss_next = state
        if not isinstance(counter, int) or isinstance(counter, bool):
            raise ValueError(f"invalid stream counter {counter!r}")
        if gauss_next is not None and not isinstance(gauss_next, float):
            raise ValueError(f"invalid cached gauss value {gauss_next!r}")
        self._state = counter & _MASK64
        self.gauss_next = gauss_next


class RandomStreams:
    """The named random streams of one run."""

    def __init__(self, seed: int) -> None:
        """Create the streams of the run with the given seed."""
        self._seed = seed
        self._streams: dict[str, Stream] = {}

    @property
    def seed(self) -> int:
        """The run seed all streams derive from."""
        return self._seed

    def stream(self, name: str) -> Stream:
        """Return the stream called *name*, creating it on first use."""
        stream = self._streams.get(name)
        if stream is None:
            stream = self._streams[name] = Stream(_derive(self._seed, name))
        return stream

    def snapshot(self) -> JsonValue:
        """Return the seed and the position of every stream used so far."""
        return {
            "seed": self._seed,
            "streams": {name: list(stream.getstate()) for name, stream in self._streams.items()},
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`, seed included.

        Generators already handed out stay valid: they are repositioned, not
        replaced. A stream first used after the snapshot was taken starts over.
        """
        if not isinstance(state, dict):
            raise ValueError("random-stream snapshot must be a mapping")
        seed, saved = state["seed"], state["streams"]
        if not isinstance(seed, int) or isinstance(seed, bool) or not isinstance(saved, dict):
            raise ValueError("malformed random-stream snapshot")
        self._seed = seed
        for name, stream in self._streams.items():
            if name not in saved:
                stream.seed(_derive(seed, name))
        for name, entry in saved.items():
            if not isinstance(entry, list | tuple) or len(entry) != 2:
                raise ValueError(f"malformed state for stream {name!r}")
            self.stream(name).setstate(tuple(entry))
