"""ADC-CTL-001 and -002: the automatic transfer sequence of SDD 7.2, one test per row."""

from collections.abc import Callable
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from agentic_datacenter.core.module import Inputs, ModuleContext
from agentic_datacenter.core.ports import ElectricalDemand, ElectricalSupply, Signal
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.plant.electrical.power_train import MODULE

LIVE = ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0)
DEAD = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)
GEN_START_MS = 10_000
# Settings used throughout, in seconds.
TDES, TDNE, TDPT, TDEN, TDEC = 5.0, 1.0, 1.0, 30.0, 300.0


class Rig:
    """One power train with a scripted utility feed and a simple generator beside it."""

    def __init__(self, seed: int = 1) -> None:
        self.kernel = Kernel(seed=seed)
        ctx = ModuleContext(
            "electrical.power_train",
            "A",
            {},
            self.kernel.clock,
            self.kernel.rng,
            self.kernel.events,
        )
        self.train = MODULE.factory(ctx, {})
        self.utility = LIVE
        self.gen_fault = False
        self.gen_can_start = True
        self.load_kw = 800.0
        self._gen_started_ms: int | None = None
        self.both_closed = False
        self.states: list[str] = []
        self.kernel.events.subscribe("ato.state", lambda e: self.states.append(e.payload["state"]))

    @property
    def io(self) -> Any:
        return self.train.io

    @property
    def now_s(self) -> float:
        return self.kernel.clock.now_ms / 1000

    def gen_ready(self) -> bool:
        started = self._gen_started_ms
        return (
            started is not None
            and not self.gen_fault
            and self.kernel.clock.now_ms - started >= GEN_START_MS
        )

    def step(self) -> None:
        request = self.train.forward_outputs()["gen_start_request"]
        assert isinstance(request, Signal)
        if request.active and self.gen_can_start:
            if self._gen_started_ms is None:
                self._gen_started_ms = self.kernel.clock.now_ms
        elif not request.active:
            self._gen_started_ms = None
        ready = self.gen_ready()
        self.train.step(
            Inputs(
                forward={
                    "utility_feed": self.utility,
                    "gen_output": LIVE if ready else DEAD,
                    "gen_ready_to_load": Signal(ready),
                    "gen_fault": Signal(self.gen_fault),
                },
                reverse={"lv_bus": ElectricalDemand(self.load_kw), "gen_start_request": None},
            )
        )
        self.kernel.clock.advance()
        if self.io["util_brk_closed"] and self.io["gen_brk_closed"]:
            self.both_closed = True

    def run(self, seconds: float) -> None:
        for _ in range(round(seconds * 10)):
            self.step()

    def until(self, condition: Callable[[], bool], limit_s: float = 600.0) -> float:
        start = self.now_s
        while not condition():
            assert self.now_s - start < limit_s, "condition not reached"
            self.step()
        return self.now_s - start

    def bus(self) -> ElectricalSupply:
        bus = self.train.forward_outputs()["lv_bus"]
        assert isinstance(bus, ElectricalSupply)
        return bus

    def on_generator(self) -> bool:
        return bool(self.io["gen_brk_closed"]) and not self.io["util_brk_closed"]

    def on_utility(self) -> bool:
        return bool(self.io["util_brk_closed"]) and not self.io["gen_brk_closed"]

    def to_generator(self) -> None:
        self.run(2)
        self.utility = DEAD
        self.until(self.on_generator)


def test_starts_on_utility_with_the_bus_live() -> None:
    rig = Rig()
    rig.run(2)
    assert rig.on_utility() and rig.bus().energized
    assert rig.io["state"] == "ON_UTILITY"


@pytest.mark.req("ADC-CTL-001")
def test_utility_loss_transfers_to_generator_in_the_order_of_the_sequence() -> None:
    rig = Rig()
    rig.run(2)
    rig.utility = DEAD
    took = rig.until(rig.on_generator)
    # TDES, generator start, TDNE, breaker opening, TDPT, breaker closing.
    expected = TDES + GEN_START_MS / 1000 + TDNE + TDPT
    assert expected <= took <= expected + 1.0
    assert rig.bus().energized
    assert not rig.both_closed
    assert rig.states == [
        "START_DELAY", "WAIT_GENERATOR", "PRE_TRANSFER", "OPENING_UTILITY",
        "NEUTRAL_TO_GENERATOR", "CLOSING_GENERATOR", "ON_GENERATOR",
    ]  # fmt: skip
    assert rig.io["transfers"] == 1


@pytest.mark.req("ADC-CTL-001")
def test_neutral_position_is_held_for_tdpt_with_both_breakers_open() -> None:
    rig = Rig()
    rig.run(2)
    rig.utility = DEAD
    rig.until(lambda: not rig.io["util_brk_closed"])
    held = rig.until(lambda: bool(rig.io["gen_brk_closed"]))
    assert TDPT <= held <= TDPT + 0.3


@pytest.mark.req("ADC-CTL-001")
def test_utility_that_recovers_before_tdes_expires_aborts_the_start() -> None:
    rig = Rig()
    rig.run(2)
    rig.utility = DEAD
    rig.run(TDES - 1.0)
    rig.utility = LIVE
    rig.run(30)
    assert rig.on_utility() and rig.io["state"] == "ON_UTILITY"
    assert "WAIT_GENERATOR" not in rig.states
    assert rig.io["gen_start_request"] is False


@pytest.mark.req("ADC-CTL-001")
def test_generator_breaker_never_closes_without_ready_to_load() -> None:
    rig = Rig()
    rig.gen_can_start = False
    rig.run(2)
    rig.utility = DEAD
    rig.run(120)
    assert rig.io["gen_brk_closed"] is False
    assert rig.io["util_brk_closed"] is True
    assert rig.io["state"] == "WAIT_GENERATOR"


@pytest.mark.req("ADC-CTL-001")
def test_utility_return_retransfers_after_tden_then_cools_the_generator_down() -> None:
    rig = Rig()
    rig.to_generator()
    rig.utility = LIVE
    took = rig.until(rig.on_utility)
    assert TDEN + TDPT <= took <= TDEN + TDPT + 1.0
    assert not rig.both_closed
    assert rig.io["gen_start_request"] is True
    cooled = rig.until(lambda: rig.io["gen_start_request"] is False, limit_s=400)
    assert TDEC - 1.0 <= cooled <= TDEC + 1.0


@pytest.mark.req("ADC-CTL-001")
def test_utility_failing_during_retransfer_keeps_the_load_on_the_generator() -> None:
    rig = Rig()
    rig.to_generator()
    rig.utility = LIVE
    rig.run(TDEN - 5.0)
    rig.utility = DEAD
    rig.run(1)
    rig.utility = LIVE
    rig.run(TDEN - 5.0)
    assert rig.on_generator(), "TDEN must restart when the utility leaves tolerance"
    rig.until(rig.on_utility, limit_s=20)


@pytest.mark.req("ADC-CTL-001")
@pytest.mark.parametrize("breaker", ["util", "gen"])
def test_protective_trip_of_a_source_breaker_locks_out_every_transfer(breaker: str) -> None:
    rig = Rig()
    if breaker == "gen":
        rig.to_generator()
    rig.run(2)
    rig.train.inject(f"{breaker}_brk_trip", kind="protective")
    rig.utility = DEAD if breaker == "util" else LIVE
    rig.run(120)
    assert rig.io["state"] == "LOCKED_OUT" and rig.io["alarm_lockout"] is True
    assert rig.io["util_brk_closed"] is False and rig.io["gen_brk_closed"] is False
    assert not rig.bus().energized
    rig.train.inject("reset")
    rig.utility = LIVE
    rig.until(rig.on_utility, limit_s=60)
    assert rig.io["alarm_lockout"] is False


@pytest.mark.req("ADC-CTL-001")
def test_generator_fault_opens_its_breaker_and_blocks_reclose_until_cleared() -> None:
    rig = Rig()
    rig.to_generator()
    rig.gen_fault = True
    rig.run(2)
    assert rig.io["gen_brk_closed"] is False and rig.io["alarm_gen_fault"] is True
    rig.run(60)
    assert rig.io["gen_brk_closed"] is False, "no reclose while the fault stands"
    rig.gen_fault = False
    rig.until(rig.on_generator, limit_s=60)
    assert rig.io["alarm_gen_fault"] is False


@pytest.mark.req("ADC-CTL-001")
def test_utility_breaker_failing_to_open_leaves_the_generator_out() -> None:
    rig = Rig()
    rig.run(2)
    rig.train.inject("util_brk_fail_open")
    rig.utility = DEAD
    rig.run(60)
    assert rig.io["alarm_util_brk_fail_open"] is True
    assert rig.io["util_brk_closed"] is True and rig.io["gen_brk_closed"] is False
    assert rig.io["gen_start_request"] is False, "the generator is stopped"


@pytest.mark.req("ADC-CTL-001")
def test_utility_breaker_failing_to_close_sends_the_load_back_to_the_generator() -> None:
    rig = Rig()
    rig.to_generator()
    rig.train.inject("util_brk_fail_close")
    rig.utility = LIVE
    rig.until(lambda: rig.io["alarm_util_brk_fail_close"] is True, limit_s=60)
    rig.until(rig.on_generator, limit_s=10)
    assert rig.bus().energized and not rig.both_closed


@pytest.mark.req("ADC-CTL-001")
def test_utility_breaker_trip_attempts_a_transfer_to_the_generator() -> None:
    rig = Rig()
    rig.run(2)
    rig.train.inject("util_brk_trip", kind="other")
    rig.until(rig.on_generator, limit_s=40)
    assert rig.utility.energized, "the utility itself never left tolerance"
    assert rig.io["state"] == "ON_GENERATOR"


@pytest.mark.req("ADC-CTL-001")
def test_generator_breaker_failing_to_open_keeps_the_utility_breaker_open() -> None:
    rig = Rig()
    rig.to_generator()
    rig.train.inject("gen_brk_fail_open")
    rig.utility = LIVE
    rig.run(TDEN + 20)
    assert rig.io["alarm_gen_brk_fail_open"] is True
    assert rig.on_generator() and rig.io["util_brk_closed"] is False


@pytest.mark.req("ADC-CTL-001")
def test_generator_breaker_failing_to_close_keeps_the_utility_breaker_closed() -> None:
    rig = Rig()
    rig.run(2)
    rig.train.inject("gen_brk_fail_close")
    rig.utility = DEAD
    rig.until(lambda: rig.io["alarm_gen_brk_fail_close"] is True, limit_s=60)
    rig.run(5)
    assert rig.io["util_brk_closed"] is True and rig.io["gen_brk_closed"] is False
    assert rig.io["gen_start_request"] is False, "the generator is stopped"


@pytest.mark.req("ADC-CTL-001")
def test_generator_breaker_trip_retransfers_at_once_without_tden() -> None:
    rig = Rig()
    rig.to_generator()
    rig.utility = LIVE
    rig.run(2)
    rig.train.inject("gen_brk_trip", kind="other")
    took = rig.until(rig.on_utility, limit_s=20)
    assert took <= TDPT + 1.0, "TDEN is skipped"


@pytest.mark.req("ADC-CTL-001")
@pytest.mark.parametrize("mode", ["MANUAL", "DISABLE"])
def test_mode_switch_out_of_auto_alarms_for_as_long_as_it_persists(mode: str) -> None:
    rig = Rig()
    rig.run(2)
    rig.train.inject("set_mode", mode=mode)
    rig.utility = DEAD
    rig.run(60)
    assert rig.io["alarm_not_in_auto"] is True
    assert rig.io["gen_start_request"] is False, "no automatic sequence outside AUTO"
    rig.train.inject("set_mode", mode="AUTO")
    rig.run(1)
    assert rig.io["alarm_not_in_auto"] is False
    rig.until(rig.on_generator, limit_s=40)


@pytest.mark.req("ADC-CTL-001")
def test_source_acceptance_uses_drop_out_and_pick_up_thresholds() -> None:
    rig = Rig()
    rig.run(2)
    rig.utility = ElectricalSupply(True, 0.93, 1.0)
    rig.run(20)
    assert rig.io["state"] == "ON_UTILITY", "0.93 pu is above the 0.90 drop-out limit"
    rig.utility = ElectricalSupply(True, 0.89, 1.0)
    rig.until(rig.on_generator, limit_s=40)
    rig.utility = ElectricalSupply(True, 0.93, 1.0)
    rig.run(TDEN + 10)
    assert rig.on_generator(), "0.93 pu is below the 0.95 pick-up limit"
    rig.utility = ElectricalSupply(True, 1.0, 0.89)
    rig.run(TDEN + 10)
    assert rig.on_generator(), "frequency is out of tolerance"
    rig.utility = LIVE
    rig.until(rig.on_utility, limit_s=TDEN + 5)


@pytest.mark.req("ADC-PRC-001")
def test_demand_is_drawn_from_the_source_that_carries_the_bus() -> None:
    rig = Rig()
    rig.run(2)
    out = rig.train.reverse_outputs()
    assert out == {"utility_feed": ElectricalDemand(800.0), "gen_output": ElectricalDemand(0.0)}
    rig.utility = DEAD
    rig.until(lambda: not rig.io["util_brk_closed"])
    rig.step()
    assert rig.train.reverse_outputs() == {
        "utility_feed": ElectricalDemand(0.0), "gen_output": ElectricalDemand(0.0),
    }  # fmt: skip
    rig.until(rig.on_generator)
    rig.step()
    assert rig.train.reverse_outputs()["gen_output"] == ElectricalDemand(800.0)


def test_timers_come_from_the_profile() -> None:
    kernel = Kernel(seed=1)
    ctx = ModuleContext("electrical.power_train", "A", {}, kernel.clock, kernel.rng, kernel.events)
    train = MODULE.factory(ctx, {"tdes_s": 3.0, "tden_s": 20.0})
    assert train.io["tdes_s"] == 3.0 and train.io["tden_s"] == 20.0 and train.io["tdpt_s"] == TDPT


def test_snapshot_taken_mid_transfer_restores_and_continues_identically() -> None:
    rig = Rig()
    rig.run(2)
    rig.utility = DEAD
    rig.run(TDES + 4)
    saved = rig.train.snapshot()
    trace = []
    for _ in range(200):
        rig.step()
        trace.append((rig.io["state"], rig.io["util_brk_closed"], rig.io["gen_brk_closed"]))
    assert trace[-1][0] == "ON_GENERATOR"
    assert isinstance(saved, dict) and saved["io"]["state"] == "WAIT_GENERATOR"


def test_steady_train_is_quiescent_and_a_running_timer_is_not() -> None:
    rig = Rig()
    rig.run(2)
    assert rig.train.quiescent()
    rig.utility = DEAD
    rig.run(1)
    assert not rig.train.quiescent()


EVENTS = st.lists(
    st.one_of(
        st.sampled_from(
            [
                ("utility", "dead"),
                ("utility", "live"),
                ("utility", "sag"),
                ("gen_fault", True),
                ("gen_fault", False),
                ("gen_can_start", True),
                ("gen_can_start", False),
                ("inject", "util_brk_fail_open"),
                ("inject", "util_brk_fail_close"),
                ("inject", "gen_brk_fail_open"),
                ("inject", "gen_brk_fail_close"),
                ("inject", "reset"),
                ("clear", "all"),
                ("trip", ("util", "protective")),
                ("trip", ("util", "other")),
                ("trip", ("gen", "protective")),
                ("trip", ("gen", "other")),
                ("mode", "AUTO"),
                ("mode", "MANUAL"),
                ("mode", "DISABLE"),
                ("manual_close", "util"),
                ("manual_close", "gen"),
                ("manual_open", "util"),
                ("manual_open", "gen"),
            ]
        ),  # fmt: skip
    ),
    min_size=1,
    max_size=25,
)


@pytest.mark.req("ADC-CTL-002")
@settings(max_examples=150, deadline=None)
@given(events=EVENTS, gaps=st.lists(st.integers(1, 400), min_size=25, max_size=25))
def test_inv_ato_1_the_two_source_breakers_are_never_both_closed(
    events: list[tuple[str, Any]], gaps: list[int]
) -> None:
    rig = Rig()
    for (kind, arg), gap in zip(events, gaps, strict=False):
        if kind == "utility":
            rig.utility = {"dead": DEAD, "live": LIVE, "sag": ElectricalSupply(True, 0.8, 1.0)}[arg]
        elif kind in ("gen_fault", "gen_can_start"):
            setattr(rig, kind, arg)
        elif kind == "inject":
            rig.train.inject(arg)
        elif kind == "clear":
            rig.train.inject("clear_faults")
        elif kind == "trip":
            rig.train.inject(f"{arg[0]}_brk_trip", kind=arg[1])
        elif kind == "mode":
            rig.train.inject("set_mode", mode=arg)
        else:
            rig.train.inject(kind, breaker=arg)
        for _ in range(gap):
            rig.step()
            assert not (rig.io["util_brk_closed"] and rig.io["gen_brk_closed"])
    assert not rig.both_closed
