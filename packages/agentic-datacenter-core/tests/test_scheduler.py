"""Kernel: fixed-step scheduling of tasks in a fixed order."""

import pytest

from agentic_datacenter.core.scheduler import Kernel


def test_step_advances_simulated_time_by_one_base_step() -> None:
    kernel = Kernel(seed=1)
    kernel.step()
    assert kernel.clock.now_ms == 100


def test_tasks_run_in_registration_order() -> None:
    kernel = Kernel(seed=1)
    calls: list[str] = []
    kernel.add_task("b", lambda: calls.append("b"))
    kernel.add_task("a", lambda: calls.append("a"))
    kernel.step()
    assert calls == ["b", "a"]


def test_task_sees_the_time_at_the_start_of_its_step() -> None:
    kernel = Kernel(seed=1)
    seen: list[int] = []
    kernel.add_task("t", lambda: seen.append(kernel.clock.now_ms))
    kernel.run(3)
    assert seen == [0, 100, 200]


def test_one_second_task_runs_every_tenth_step() -> None:
    kernel = Kernel(seed=1)
    seen: list[int] = []
    kernel.add_task("thermal", lambda: seen.append(kernel.clock.now_ms), period_ms=1000)
    kernel.run_for(2500)
    assert seen == [0, 1000, 2000]


@pytest.mark.parametrize("period_ms", [0, -100, 150])
def test_period_must_be_a_positive_multiple_of_the_base_step(period_ms: int) -> None:
    with pytest.raises(ValueError, match="period_ms"):
        Kernel(seed=1).add_task("t", lambda: None, period_ms=period_ms)


def test_duplicate_task_name_is_refused() -> None:
    kernel = Kernel(seed=1)
    kernel.add_task("t", lambda: None)
    with pytest.raises(ValueError, match="'t'"):
        kernel.add_task("t", lambda: None)


def test_run_for_refuses_a_duration_that_is_not_whole_steps() -> None:
    with pytest.raises(ValueError, match="duration_ms"):
        Kernel(seed=1).run_for(250)


def test_state_hash_covers_clock_and_seed() -> None:
    a, b, other_seed = Kernel(seed=1), Kernel(seed=1), Kernel(seed=2)
    assert a.state_hash() == b.state_hash()
    assert a.state_hash() != other_seed.state_hash()
    a.step()
    assert a.state_hash() != b.state_hash()


def test_part_registered_under_a_kernel_name_is_refused() -> None:
    kernel = Kernel(seed=1)
    with pytest.raises(ValueError, match="kernel.clock"):
        kernel.state.register("kernel.clock", kernel.clock)
