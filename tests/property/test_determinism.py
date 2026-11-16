"""ADC-KRN-001: same inputs and seed give the same state hash at every step."""

import os
import subprocess
import sys
from collections.abc import Callable

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agentic_datacenter.core.scheduler import Kernel

seeds = st.integers(min_value=0, max_value=2**63 - 1)


def hashes(kernel: Kernel, steps: int) -> list[str]:
    out = []
    for _ in range(steps):
        kernel.step()
        out.append(kernel.state_hash())
    return out


@pytest.mark.req("ADC-KRN-001")
@given(seed=seeds, steps=st.integers(min_value=1, max_value=300))
def test_two_runs_with_one_seed_agree_at_every_step(
    toy: Callable[[int], Kernel], seed: int, steps: int
) -> None:
    assert hashes(toy(seed), steps) == hashes(toy(seed), steps)


@pytest.mark.req("ADC-KRN-001")
@given(seed=seeds)
def test_the_hash_changes_at_every_step(toy: Callable[[int], Kernel], seed: int) -> None:
    run = hashes(toy(seed), 50)
    assert len(set(run)) == 50


@pytest.mark.req("ADC-KRN-001")
@given(a=seeds, b=seeds)
def test_different_seeds_diverge(toy: Callable[[int], Kernel], a: int, b: int) -> None:
    if a != b:
        assert hashes(toy(a), 20) != hashes(toy(b), 20)


SCRIPT = """
from agentic_datacenter.core.scheduler import Kernel

class Part:
    def __init__(self, kernel):
        self.rng = kernel.rng.stream("part")
        self.values = {}
    def step(self):
        key = "k%d" % self.rng.randrange(50)
        self.values[key] = self.values.get(key, 0.0) + self.rng.gauss(0.0, 1.0)
    def snapshot(self):
        return {"values": self.values, "names": sorted({k for k in self.values})}
    def restore(self, state):
        raise NotImplementedError

kernel = Kernel(seed=20261112)
part = Part(kernel)
kernel.state.register("part", part)
kernel.add_task("part", part.step)
kernel.run(500)
print(kernel.state_hash())
"""


@pytest.mark.req("ADC-KRN-001")
def test_hash_does_not_depend_on_the_interpreter_hash_seed() -> None:
    def run(hash_seed: str) -> str:
        env = {**os.environ, "PYTHONHASHSEED": hash_seed}
        done = subprocess.run(
            [sys.executable, "-c", SCRIPT], env=env, capture_output=True, text=True, check=True
        )
        return done.stdout.strip()

    first, second = run("1"), run("987654")
    assert len(first) == 64
    assert first == second
