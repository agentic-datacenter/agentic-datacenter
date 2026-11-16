"""ADC-KRN-004: 24 simulated hours of the generic profile in under 60 s.

Runs in the nightly workflow (SDD 12.4), where the per-commit trend is kept.
The budget includes a state hash at every simulated second, which is the
default evidence interval (ADR 0006).
"""

from pathlib import Path

import pytest

from agentic_datacenter.core.clock import wall_seconds
from agentic_datacenter.core.profile import build_plant, load_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel

REPO = Path(__file__).resolve().parents[2]
STEPS_PER_SECOND = 10


@pytest.mark.nightly
@pytest.mark.req("ADC-KRN-004")
def test_24_simulated_hours_run_in_under_60_seconds() -> None:
    kernel = Kernel(seed=1)
    build_plant(
        load_profile(REPO / "profiles/generic_dc.yaml"), kernel, ModuleRegistry.from_entry_points()
    )
    start = wall_seconds()
    for _ in range(24 * 3600):
        kernel.run(STEPS_PER_SECOND)
        kernel.state_hash()
    elapsed = wall_seconds() - start
    assert kernel.clock.now_ms == 24 * 3600 * 1000
    assert elapsed < 60.0, f"24 simulated hours took {elapsed:.1f} s"
