"""ADC-KRN-002: snapshot at any step, restore, and continue identically."""

from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agentic_datacenter.core.scheduler import Kernel

seeds = st.integers(min_value=0, max_value=2**63 - 1)
before = st.integers(min_value=0, max_value=150)
after = st.integers(min_value=1, max_value=150)


def hashes(kernel: Kernel, steps: int) -> list[str]:
    out = []
    for _ in range(steps):
        kernel.step()
        out.append(kernel.state_hash())
    return out


@pytest.mark.req("ADC-KRN-002")
@given(seed=seeds, n=before, m=after)
def test_restore_into_the_same_kernel_replays_the_continuation(
    toy: Callable[[int], Kernel], seed: int, n: int, m: int
) -> None:
    kernel = toy(seed)
    kernel.run(n)
    saved = kernel.snapshot()
    expected = hashes(kernel, m)
    kernel.restore(saved)
    assert hashes(kernel, m) == expected


@pytest.mark.req("ADC-KRN-002")
@given(seed=seeds, other_seed=seeds, n=before, m=after)
def test_restore_into_a_fresh_kernel_replays_the_continuation(
    toy: Callable[[int], Kernel], seed: int, other_seed: int, n: int, m: int
) -> None:
    source = toy(seed)
    source.run(n)
    saved = source.snapshot()
    expected = hashes(source, m)
    fresh = toy(other_seed)
    fresh.run(3)
    fresh.restore(saved)
    assert hashes(fresh, m) == expected


@pytest.mark.req("ADC-KRN-002")
@given(seed=seeds, n=before)
def test_taking_a_snapshot_does_not_change_the_run(
    toy: Callable[[int], Kernel], seed: int, n: int
) -> None:
    observed, plain = toy(seed), toy(seed)
    for _ in range(n):
        observed.step()
        observed.snapshot()
        plain.step()
    assert observed.state_hash() == plain.state_hash()


@pytest.mark.req("ADC-KRN-002")
@given(seed=seeds, n=before)
def test_snapshot_survives_a_json_round_trip(
    toy: Callable[[int], Kernel], seed: int, n: int
) -> None:
    import json

    kernel = toy(seed)
    kernel.run(n)
    saved = json.loads(json.dumps(kernel.snapshot()))
    expected = hashes(kernel, 20)
    kernel.restore(saved)
    assert hashes(kernel, 20) == expected
