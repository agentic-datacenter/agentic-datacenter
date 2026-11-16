"""Append-only, hash-chained logs (SDD 7.5, ADC-SUP-002).

The alarm log and the audit log are instances of this. An entry is numbered,
timed and carries the hash of the entry before it. There is no way to change
or remove an entry through the interface: an attempt is refused and is itself
written to the log.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import NoReturn

from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue, state_hash

RESERVED = ("seq", "time_ms", "kind", "prev", "hash")
GENESIS = "0" * 64


class LogIntegrityError(RuntimeError):
    """Something tried to modify, delete or truncate an append-only log."""


class AppendOnlyLog:
    """One append-only log, part of the simulation state."""

    def __init__(self, kernel: Kernel, name: str) -> None:
        """Create the empty log *name*."""
        self._kernel = kernel
        self.name = name
        self._part = f"supervisory.log.{name}"
        self._entries: list[dict[str, JsonValue]] = []
        kernel.state.register(self._part, self, tracked=True)

    def __len__(self) -> int:
        """Return the number of entries."""
        return len(self._entries)

    def append(self, kind: str, **fields: JsonValue) -> dict[str, JsonValue]:
        """Add one entry of *kind* and return a copy of it.

        Raises:
            ValueError: If *fields* names a field the log sets itself.
        """
        taken = [name for name in RESERVED if name in fields]
        if taken:
            raise ValueError(f"the log sets these itself: {', '.join(taken)}")
        entry: dict[str, JsonValue] = {
            "seq": len(self._entries),
            "time_ms": self._kernel.clock.now_ms,
            "kind": kind,
            **fields,
            "prev": self._entries[-1]["hash"] if self._entries else GENESIS,
        }
        entry["hash"] = state_hash(entry)
        self._entries.append(entry)
        self._kernel.state.touch(self._part)
        return copy.deepcopy(entry)

    def entries(self, since_seq: int = 0) -> list[dict[str, JsonValue]]:
        """Return a copy of every entry from *since_seq* on."""
        return copy.deepcopy(self._entries[since_seq:])

    def verify(self) -> bool:
        """Return whether every entry still matches its hash and its predecessor."""
        previous: JsonValue = GENESIS
        for seq, entry in enumerate(self._entries):
            body = {k: v for k, v in entry.items() if k != "hash"}
            if (
                entry["seq"] != seq
                or entry["prev"] != previous
                or entry["hash"] != state_hash(body)
            ):
                return False
            previous = entry["hash"]
        return True

    def _refuse(self, attempt: str, actor: str, detail: str) -> NoReturn:
        self.append("integrity_violation", attempt=attempt, actor=actor, detail=detail)
        raise LogIntegrityError(f"log {self.name!r} is append-only: {attempt} refused ({detail})")

    def modify(self, seq: int, actor: str, changes: Mapping[str, JsonValue]) -> NoReturn:
        """Refuse to change entry *seq*, and log the attempt."""
        self._refuse("modify", actor, f"entry {seq}, fields {', '.join(sorted(changes))}")

    def delete(self, seq: int, actor: str) -> NoReturn:
        """Refuse to delete entry *seq*, and log the attempt."""
        self._refuse("delete", actor, f"entry {seq}")

    def truncate(self, length: int, actor: str) -> NoReturn:
        """Refuse to shorten the log to *length* entries, and log the attempt."""
        self._refuse("truncate", actor, f"to {length} entries")

    def snapshot(self) -> JsonValue:
        """Return every entry."""
        return copy.deepcopy(self._entries)

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`.

        Restoring a whole simulation state is how a run is replayed; it is not
        reachable from the operator or agent interfaces.
        """
        if not isinstance(state, list):
            raise ValueError("log snapshot must be a list")
        self._entries = [dict(e) for e in state if isinstance(e, Mapping)]
