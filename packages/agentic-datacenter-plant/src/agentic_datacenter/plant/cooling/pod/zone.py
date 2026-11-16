"""The zone sensor array of one POD and its mean.

A sensor leaves the mean for one of three reasons (SDD 6.5, 7.3):

- ``bad_quality``: the sensor reports bad quality. It leaves in the same
  control step and returns by itself when its quality is good again.
- ``cross_check``: it has disagreed with the median of the others by more than
  the band for longer than the hold time. That catches a drifting sensor.
- ``stuck``: it has not changed for longer than the stuck time while the median
  of the others moved. Nothing can show a stuck sensor while the hall is steady.

The last two are latched until the sensor is reset.
"""

from __future__ import annotations

from statistics import median

from agentic_datacenter.core.state import JsonValue

#: Fixed spread of the six sensors about the zone temperature (assumed gradient).
ZONE_OFFSETS_K = (-0.15, -0.09, -0.03, 0.03, 0.09, 0.15)
CROSS_CHECK_BAND_K = 2.0
CROSS_CHECK_HOLD_S = 30
STUCK_AFTER_S = 120
STUCK_MEDIAN_MOVE_K = 0.3


class ZoneArray:
    """Readings of the zone sensors and which of them the mean uses."""

    def __init__(self, start_c: float) -> None:
        """Create an array with every sensor in the mean."""
        count = len(ZONE_OFFSETS_K)
        self.value = [start_c] * count
        self.good = [True] * count
        self.excluded = [""] * count
        self.deviant_since = [-1] * count
        self.same_since = [0] * count
        self.same_median = [start_c] * count

    def _others(self, index: int) -> list[float]:
        return [
            v for i, v in enumerate(self.value)
            if i != index and self.good[i] and not self.excluded[i]
        ]  # fmt: skip

    def update(self, index: int, reading: float, good: bool, now_s: int) -> str:
        """Take one reading; return the reason if the sensor leaves the mean now."""
        changed = reading != self.value[index]
        self.value[index], self.good[index] = reading, good
        was = self.excluded[index]
        if not good:
            self.excluded[index] = was or "bad_quality"
            return "" if was else "bad_quality"
        if was == "bad_quality":
            self.excluded[index] = was = ""
        others = self._others(index)
        if was or not others:
            return ""
        middle = median(others)
        if changed:
            self.same_since[index], self.same_median[index] = now_s, middle
        if abs(reading - middle) <= CROSS_CHECK_BAND_K:
            self.deviant_since[index] = -1
        elif self.deviant_since[index] < 0:
            self.deviant_since[index] = now_s
        elif now_s - self.deviant_since[index] >= CROSS_CHECK_HOLD_S:
            self.excluded[index] = "cross_check"
            return "cross_check"
        moved = abs(middle - self.same_median[index]) > STUCK_MEDIAN_MOVE_K
        if moved and now_s - self.same_since[index] >= STUCK_AFTER_S:
            self.excluded[index] = "stuck"
            return "stuck"
        return ""

    def used(self) -> int:
        """Return how many sensors the mean uses."""
        return sum(
            1 for good, out in zip(self.good, self.excluded, strict=True) if good and not out
        )

    def mean(self) -> float | None:
        """Return the mean of the sensors in use, or None when there is none."""
        values = [
            v for v, good, out in zip(self.value, self.good, self.excluded, strict=True)
            if good and not out
        ]  # fmt: skip
        return sum(values) / len(values) if values else None

    def quiet(self) -> bool:
        """No cross-check timer is running."""
        return all(since < 0 for since in self.deviant_since)

    def snapshot(self) -> JsonValue:
        """Return the complete state of the array."""
        return [
            list(self.value),
            list(self.good),
            list(self.excluded),
            list(self.deviant_since),
            list(self.same_since),
            list(self.same_median),
        ]

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, list | tuple) or len(state) != 6:
            raise ValueError("zone-array snapshot is malformed")
        value, good, excluded, deviant, same_since, same_median = state
        self.value = [float(str(v)) for v in value]  # type: ignore[union-attr]
        self.good = [bool(v) for v in good]  # type: ignore[union-attr]
        self.excluded = [str(v) for v in excluded]  # type: ignore[union-attr]
        self.deviant_since = [int(str(v)) for v in deviant]  # type: ignore[union-attr]
        self.same_since = [int(str(v)) for v in same_since]  # type: ignore[union-attr]
        self.same_median = [float(str(v)) for v in same_median]  # type: ignore[union-attr]
