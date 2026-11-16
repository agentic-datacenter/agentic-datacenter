"""Failure modes of a sensor (SDD 6.5). Each takes ``tag``: ``module_id[instance].point``.

- ``stuck``: the reading stays at its last value.
- ``drift``: the reading moves away from the truth by ``rate_per_min``.
- ``bias``: the reading is off by ``offset`` (false data, as in scenario AD-03).
- ``noisy``: Gaussian noise of standard deviation ``sigma`` is added.
- ``bad``: the reading is flagged bad quality.
- ``clear``: the sensor is healthy again.
"""

from __future__ import annotations

MODES = ("stuck", "drift", "bias", "noisy", "bad", "clear")
