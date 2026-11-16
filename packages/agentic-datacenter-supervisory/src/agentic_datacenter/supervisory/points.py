"""The point database: the supervisory layer's view of every module point.

One database is the single source of truth for everything above the
controllers (SDD 8). It reads the I/O boards of the plant modules; nothing in
it is computed twice. A value carries its quality and the time it was polled.

The supervisory network can be cut (scenario OP-08). The controllers go on;
the database keeps the last values it polled and marks them stale after three
missed polls (SDD 8.4).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agentic_datacenter.core.io import IOBoard, PointDecl, PointValue
from agentic_datacenter.core.module import SimModule
from agentic_datacenter.core.registry import Plant
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue

POLL_MS = 1000
STALE_AFTER_MISSED = 3


@dataclass(frozen=True)
class PointRecord:
    """One point as the supervisory layer sees it."""

    tag: str
    value: PointValue
    quality: str
    time_ms: int
    kind: str
    tier: str
    unit: str
    range: tuple[float, float] | None
    description: str
    zone: str


class PointDatabase:
    """Every point of every module, by tag ``module_id[instance].point``."""

    def __init__(self, kernel: Kernel, plant: Plant) -> None:
        """Index the plant's I/O boards and start polling once a second."""
        self._kernel = kernel
        self._boards: dict[str, IOBoard] = {}
        self._modules: dict[str, SimModule] = {}
        self._zones: dict[str, str] = {}
        self._module_ids: dict[str, str] = {}
        for name, manifest, module in plant.instances():
            board = getattr(module, "io", None)
            if isinstance(board, IOBoard):
                self._boards[name] = board
                self._modules[name] = module
                self._zones[name] = manifest.zone_for(module.ctx.instance)
                self._module_ids[name] = manifest.id
        #: Tag -> (instance, point). Tags and boards are fixed once the plant is built.
        self._split_cache: dict[str, tuple[str, str]] = {}
        self._tags = sorted(
            f"{name}.{point}" for name, board in self._boards.items() for point in board
        )
        self._link_up = True
        self._missed = 0
        self._polled_ms = kernel.clock.now_ms
        self._frozen: dict[str, PointValue] | None = None
        kernel.state.register("supervisory.points", self, tracked=True)
        kernel.add_task("supervisory.poll", self._poll, period_ms=POLL_MS)

    def _split(self, tag: str) -> tuple[str, str]:
        split = self._split_cache.get(tag)
        if split is not None:
            return split
        name, _, point = tag.rpartition(".")
        if name not in self._boards or point not in self._boards[name]:
            raise KeyError(f"no such point: {tag}")
        self._split_cache[tag] = (name, point)
        return name, point

    def value_and_quality(self, tag: str) -> tuple[PointValue, str]:
        """Return the value of point *tag* and its quality, as :meth:`read` would.

        For a reader that needs nothing else, such as the alarm scan, many
        times a second.

        Raises:
            KeyError: If there is no such point.
        """
        name, point = self._split(tag)
        if self._frozen is None:
            return self._boards[name][point], "good"
        return self._frozen[tag], "stale" if self._missed >= STALE_AFTER_MISSED else "good"

    def _poll(self) -> None:
        # While the link is up the poll time follows the clock and nothing is
        # stored, so this part of the state does not change every second.
        if self._link_up:
            return
        self._missed += 1
        self._kernel.state.touch("supervisory.points")

    @property
    def link_up(self) -> bool:
        """Whether the supervisory network reaches the controllers."""
        return self._link_up

    def set_link(self, up: bool) -> None:
        """Cut or restore the supervisory network. The controllers are not affected."""
        if up == self._link_up:
            return
        self._link_up, self._missed = up, 0
        self._polled_ms = self._kernel.clock.now_ms // POLL_MS * POLL_MS
        if up:
            self._frozen = None
        else:
            self._frozen = {
                tag: self._boards[n][p] for tag in self._tags for n, p in [self._split(tag)]
            }
        self._kernel.state.touch("supervisory.points")
        self._kernel.events.publish("supervisory.link", {"up": up})

    def freshness(self) -> tuple[str, int]:
        """Return the quality of what the database holds now, and when it was polled."""
        if self._frozen is None:
            return "good", self._kernel.clock.now_ms // POLL_MS * POLL_MS
        return ("stale" if self._missed >= STALE_AFTER_MISSED else "good"), self._polled_ms

    def tags(self) -> list[str]:
        """Return every tag, sorted."""
        return list(self._tags)

    def declaration(self, tag: str) -> PointDecl:
        """Return the declaration of point *tag*."""
        name, point = self._split(tag)
        return self._boards[name].declaration(point)

    def read(self, tag: str) -> PointRecord:
        """Return point *tag* with its quality and poll time.

        Raises:
            KeyError: If there is no such point.
        """
        name, point = self._split(tag)
        decl = self._boards[name].declaration(point)
        if self._frozen is None:
            value, quality = self._boards[name][point], "good"
            time_ms = self._kernel.clock.now_ms // POLL_MS * POLL_MS
        else:
            value = self._frozen[tag]
            quality = "stale" if self._missed >= STALE_AFTER_MISSED else "good"
            time_ms = self._polled_ms
        return PointRecord(
            tag,
            value,
            quality,
            time_ms,
            decl.kind,
            decl.tier,
            decl.unit,
            decl.range,
            decl.description,
            self._zones[name],
        )

    def find(self, module_id: str, point: str) -> list[PointRecord]:
        """Return point *point* of every instance of module *module_id*."""
        return [
            self.read(f"{name}.{point}")
            for name in sorted(self._boards)
            if self._module_ids[name] == module_id and point in self._boards[name]
        ]

    def write_through(self, tag: str, value: PointValue) -> PointValue:
        """Write a point on its module's board and wake the module. For the command service."""
        name, point = self._split(tag)
        board = self._boards[name]
        old = board[point]
        board[point] = value
        self._modules[name].ctx.wake()
        return old

    def snapshot(self) -> JsonValue:
        """Return the link state and, while the link is down, the values last polled."""
        frozen: JsonValue = dict(self._frozen) if self._frozen is not None else None
        return {
            "link_up": self._link_up,
            "missed": self._missed,
            "polled_ms": self._polled_ms,
            "frozen": frozen,
        }

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("point-database snapshot must be a mapping")
        frozen = state["frozen"]
        self._link_up, self._missed = bool(state["link_up"]), int(str(state["missed"]))
        self._polled_ms = int(str(state["polled_ms"]))
        self._frozen = dict(frozen) if isinstance(frozen, Mapping) else None  # type: ignore[arg-type]
