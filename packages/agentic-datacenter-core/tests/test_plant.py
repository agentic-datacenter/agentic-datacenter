"""Registry and wiring: modules meet only through declared, typed ports."""

from collections.abc import Mapping
from typing import Any

import pytest

from agentic_datacenter.core.module import (
    Inputs,
    LazyIntegral,
    ModuleContext,
    ModuleContractError,
    SimModule,
    parse_manifest,
)
from agentic_datacenter.core.ports import ElectricalDemand, ElectricalSupply, Signal
from agentic_datacenter.core.registry import Connection, InstanceSpec, ModuleRegistry, WiringError
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue

LIVE = ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0)
DEAD = ElectricalSupply(energized=False, voltage_pu=0.0, frequency_pu=0.0)


def manifest(module_id: str, provides: list[dict[str, str]], requires: list[dict[str, str]]) -> Any:
    return parse_manifest(
        {
            "id": module_id,
            "version": "0.1.0",
            "fidelity": "F0",
            "provides": provides,
            "requires": requires,
            "zone": "Z-TEST",
            "requirements": ["ADC-MOD-004"],
            "spec": f"docs/design/modules/{module_id}.md",
        }
    )


class Source(SimModule):
    """Energized from the step given in ``on_at_step``; records the demand it sees."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        super().__init__(ctx, params)
        on_at = params.get("on_at_step", 0)
        assert isinstance(on_at, int)
        self.on_at = on_at
        self.steps = 0
        self.seen_kw: list[float] = []

    def step(self, inputs: Inputs) -> None:
        demand = inputs.reverse["out"]
        assert isinstance(demand, ElectricalDemand)
        self.seen_kw.append(demand.kw)
        self.steps += 1

    def forward_outputs(self) -> Mapping[str, object]:
        return {"out": LIVE if self.steps >= self.on_at else DEAD}

    def snapshot(self) -> JsonValue:
        return {"steps": self.steps, "seen_kw": list(self.seen_kw)}

    def restore(self, state: JsonValue) -> None:
        assert isinstance(state, dict)
        steps, seen = state["steps"], state["seen_kw"]
        assert isinstance(steps, int) and isinstance(seen, list)
        self.steps, self.seen_kw = steps, [float(v) for v in seen]  # type: ignore[arg-type]


class Load(SimModule):
    """Draws ``kw`` (with seeded noise) whenever its feed is energized."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        super().__init__(ctx, params)
        kw = params.get("kw", 10.0)
        assert isinstance(kw, float)
        self.kw = kw
        self.noise = ctx.rng("noise")
        self.seen: list[bool] = []
        self.draw = 0.0

    def step(self, inputs: Inputs) -> None:
        feed = inputs.forward["feed"]
        assert isinstance(feed, ElectricalSupply)
        self.seen.append(feed.energized)
        self.draw = self.kw + self.noise.uniform(0.0, 0.001) if feed.energized else 0.0

    def forward_outputs(self) -> Mapping[str, object]:
        return {}

    def reverse_outputs(self) -> Mapping[str, object]:
        return {"feed": ElectricalDemand(kw=self.draw)}

    def snapshot(self) -> JsonValue:
        return {"seen": list(self.seen), "draw": self.draw}

    def restore(self, state: JsonValue) -> None:
        assert isinstance(state, dict)
        seen, draw = state["seen"], state["draw"]
        assert isinstance(seen, list) and isinstance(draw, float)
        self.seen, self.draw = [bool(v) for v in seen], draw


class LoadStub(Load):
    """Stub: draws nothing, whatever the feed."""

    def step(self, inputs: Inputs) -> None:
        self.draw = 0.0


class Board(SimModule):
    """One feeder per key; only feeder A is live."""

    def step(self, inputs: Inputs) -> None:
        self.seen = {key: inputs.reverse[f"feeder[{key}]"] for key in self.ctx.keys["trains"]}

    def forward_outputs(self) -> Mapping[str, object]:
        return {f"feeder[{k}]": LIVE if k == "A" else DEAD for k in self.ctx.keys["trains"]}

    def snapshot(self) -> JsonValue:
        return {}

    def restore(self, state: JsonValue) -> None:
        pass


class WrongType(Source):
    def forward_outputs(self) -> Mapping[str, object]:
        return {"out": Signal(active=True)}


class ExtraPort(Source):
    def forward_outputs(self) -> Mapping[str, object]:
        return {"out": LIVE, "secret": LIVE}


SOURCE = manifest("test.source", [{"port": "out", "type": "electrical"}], [])
LOAD = manifest("test.load", [], [{"port": "feed", "type": "electrical"}])
BOARD = manifest("test.board", [{"port": "feeder", "type": "electrical", "keyed_by": "trains"}], [])
SENSOR = manifest("test.sensor", [], [{"port": "feed", "type": "signal"}])


def registry() -> ModuleRegistry:
    reg = ModuleRegistry()
    reg.register(SOURCE, Source, Source)
    reg.register(LOAD, Load, LoadStub)
    reg.register(BOARD, Board, Board)
    reg.register(SENSOR, Load, Load)
    return reg


def two_loads(source_params: dict[str, JsonValue] | None = None) -> tuple[Kernel, Any]:
    kernel = Kernel(seed=5)
    plant = registry().build(
        kernel,
        instances=[
            InstanceSpec("test.source", "S1", params=source_params or {}),
            InstanceSpec("test.load", "L1", params={"kw": 150.0}),
            InstanceSpec("test.load", "L2", params={"kw": 75.0}),
        ],
        connections=[
            Connection("test.load[L1].feed", "test.source[S1].out"),
            Connection("test.load[L2].feed", "test.source[S1].out"),
        ],
    )
    return kernel, plant


def test_consumer_sees_the_provider_output_of_the_previous_step() -> None:
    # The source has taken two steps, and so is live, at the end of step 1.
    # The load reads that at step 2: one step later, never in the same step.
    kernel, plant = two_loads({"on_at_step": 2})
    kernel.run(5)
    assert plant.module("test.load", "L1").seen == [False, False, True, True, True]


def test_provider_receives_the_summed_demand_of_its_consumers() -> None:
    kernel, plant = two_loads()
    kernel.run(3)
    seen = plant.module("test.source", "S1").seen_kw
    assert seen[0] == 0.0
    assert seen[2] == pytest.approx(225.0, abs=0.01)


@pytest.mark.req("ADC-MOD-002")
def test_keyed_port_keeps_each_key_apart() -> None:
    kernel = Kernel(seed=5)
    plant = registry().build(
        kernel,
        instances=[
            InstanceSpec("test.board", "MV", keys={"trains": ("A", "B")}),
            InstanceSpec("test.load", "LA", params={"kw": 10.0}),
            InstanceSpec("test.load", "LB", params={"kw": 20.0}),
        ],
        connections=[
            Connection("test.load[LA].feed", "test.board[MV].feeder[A]"),
            Connection("test.load[LB].feed", "test.board[MV].feeder[B]"),
        ],
    )
    kernel.run(3)
    assert plant.module("test.load", "LA").seen[-1] is True
    assert plant.module("test.load", "LB").seen[-1] is False
    board = plant.module("test.board", "MV")
    assert board.seen["A"].kw == pytest.approx(10.0, abs=0.01)
    assert board.seen["B"] == ElectricalDemand(kw=0.0)


@pytest.mark.req("ADC-MOD-004")
@pytest.mark.parametrize(
    ("instances", "connections", "message"),
    [
        ([InstanceSpec("test.load", "L1")], [], r"test\.load\[L1\]\.feed is not connected"),
        (
            [InstanceSpec("test.load", "L1")],
            [Connection("test.load[L1].feed", "test.source[S9].out")],
            r"test\.source\[S9\]",
        ),
        (
            [InstanceSpec("test.load", "L1"), InstanceSpec("test.source", "S1")],
            [Connection("test.load[L1].feed", "test.source[S1].nothing")],
            "nothing",
        ),
        (
            [InstanceSpec("test.sensor", "X"), InstanceSpec("test.source", "S1")],
            [Connection("test.sensor[X].feed", "test.source[S1].out")],
            "signal.*electrical|electrical.*signal",
        ),
        (
            [InstanceSpec("test.load", "L1"), InstanceSpec("test.source", "S1")],
            [
                Connection("test.load[L1].feed", "test.source[S1].out"),
                Connection("test.load[L1].feed", "test.source[S1].out"),
            ],
            "more than once",
        ),
        ([InstanceSpec("test.nothing", "N")], [], r"test\.nothing"),
        ([InstanceSpec("test.source", "S1"), InstanceSpec("test.source", "S1")], [], "S1"),
        ([InstanceSpec("test.board", "MV")], [], "trains"),
        (
            [
                InstanceSpec("test.board", "MV", keys={"trains": ("A",)}),
                InstanceSpec("test.load", "L1"),
            ],
            [Connection("test.load[L1].feed", "test.board[MV].feeder[Z]")],
            r"feeder\[Z\]",
        ),
        (
            [
                InstanceSpec("test.board", "MV", keys={"trains": ("A",)}),
                InstanceSpec("test.load", "L1"),
            ],
            [Connection("test.load[L1].feed", "test.board[MV].feeder")],
            "key",
        ),
        (
            [InstanceSpec("test.load", "L1"), InstanceSpec("test.source", "S1")],
            [Connection("not an endpoint", "test.source[S1].out")],
            "not an endpoint",
        ),
    ],
)
def test_bad_wiring_is_refused_before_the_run_starts(
    instances: list[InstanceSpec], connections: list[Connection], message: str
) -> None:
    with pytest.raises(WiringError, match=message):
        registry().build(Kernel(seed=1), instances=instances, connections=connections)


@pytest.mark.req("ADC-MOD-002")
@pytest.mark.parametrize("factory", [WrongType, ExtraPort])
def test_module_that_breaks_its_manifest_is_refused(factory: type[SimModule]) -> None:
    reg = ModuleRegistry()
    reg.register(SOURCE, factory, factory)
    with pytest.raises(ModuleContractError, match=r"test\.source\[S1\]"):
        reg.build(Kernel(seed=1), instances=[InstanceSpec("test.source", "S1")], connections=[])


def hashes(order: list[str], steps: int = 30) -> list[str]:
    specs = {
        "S1": InstanceSpec("test.source", "S1", params={"on_at_step": 3}),
        "L1": InstanceSpec("test.load", "L1", params={"kw": 150.0}),
        "L2": InstanceSpec("test.load", "L2", params={"kw": 75.0}),
    }
    kernel = Kernel(seed=11)
    registry().build(
        kernel,
        instances=[specs[name] for name in order],
        connections=[
            Connection("test.load[L1].feed", "test.source[S1].out"),
            Connection("test.load[L2].feed", "test.source[S1].out"),
        ],
    )
    out = []
    for _ in range(steps):
        kernel.step()
        out.append(kernel.state_hash())
    return out


@pytest.mark.req("ADC-KRN-001")
def test_order_in_which_instances_are_listed_does_not_change_the_run() -> None:
    assert hashes(["S1", "L1", "L2"]) == hashes(["L2", "S1", "L1"])


@pytest.mark.req("ADC-KRN-002")
def test_plant_restores_and_continues_identically() -> None:
    kernel, _ = two_loads({"on_at_step": 4})
    kernel.run(6)
    saved = kernel.snapshot()
    expected = []
    for _ in range(10):
        kernel.step()
        expected.append(kernel.state_hash())
    kernel.restore(saved)
    replay = []
    for _ in range(10):
        kernel.step()
        replay.append(kernel.state_hash())
    assert replay == expected


def test_two_instances_of_one_module_draw_from_different_streams() -> None:
    kernel, plant = two_loads()
    kernel.run(3)
    l1, l2 = plant.module("test.load", "L1"), plant.module("test.load", "L2")
    assert l1.draw - 150.0 != l2.draw - 75.0


@pytest.mark.req("ADC-MOD-004")
def test_module_can_be_swapped_for_its_stub() -> None:
    kernel = Kernel(seed=5)
    plant = registry().build(
        kernel,
        instances=[
            InstanceSpec("test.source", "S1"),
            InstanceSpec("test.load", "L1", params={"kw": 150.0}, stub=True),
        ],
        connections=[Connection("test.load[L1].feed", "test.source[S1].out")],
    )
    kernel.run(3)
    assert isinstance(plant.module("test.load", "L1"), LoadStub)
    assert plant.module("test.source", "S1").seen_kw == [0.0, 0.0, 0.0]


@pytest.mark.req("ADC-MOD-004")
def test_plant_runs_with_a_subset_whose_required_ports_are_satisfied() -> None:
    kernel = Kernel(seed=5)
    plant = registry().build(kernel, instances=[InstanceSpec("test.source", "S1")], connections=[])
    kernel.run(3)
    assert plant.module("test.source", "S1").seen_kw == [0.0, 0.0, 0.0]


def test_slow_step_runs_once_a_second_before_the_fast_step() -> None:
    calls: list[tuple[str, int]] = []

    class TwoRate(Source):
        def step_slow(self, inputs: Inputs) -> None:
            calls.append(("slow", self.ctx.now_ms))

        def step(self, inputs: Inputs) -> None:
            super().step(inputs)
            calls.append(("fast", self.ctx.now_ms))

    reg = ModuleRegistry()
    reg.register(SOURCE, TwoRate, TwoRate)
    kernel = Kernel(seed=1)
    reg.build(kernel, instances=[InstanceSpec("test.source", "S1")], connections=[])
    kernel.run(11)
    assert calls[:2] == [("slow", 0), ("fast", 0)]
    assert [c for c in calls if c[0] == "slow"] == [("slow", 0), ("slow", 1000)]


def test_registry_refuses_a_second_module_with_the_same_id() -> None:
    reg = registry()
    with pytest.raises(ValueError, match=r"test\.source"):
        reg.register(SOURCE, Source, Source)


def test_wiring_lists_every_connection_for_the_graph() -> None:
    _, plant = two_loads()
    assert plant.wiring() == [
        ("test.load[L1].feed", "test.source[S1].out", "electrical"),
        ("test.load[L2].feed", "test.source[S1].out", "electrical"),
    ]


@pytest.mark.req("ADC-MOD-005")
def test_lock_data_lists_modules_sorted_with_version_fidelity_and_requirements() -> None:
    lock = registry().lock_data()
    assert [m["id"] for m in lock["modules"]] == [
        "test.board",
        "test.load",
        "test.sensor",
        "test.source",
    ]
    assert lock["modules"][1] == {
        "id": "test.load",
        "version": "0.1.0",
        "fidelity": "F0",
        "provides": [],
        "requires": ["feed:electrical"],
        "requirements": ["ADC-MOD-004"],
        "spec": "docs/design/modules/test.load.md",
    }


def test_port_type_without_a_reverse_value_can_be_connected() -> None:
    """Regression: a signal consumer reports nothing back, and that must not break the provider."""

    class Contact(SimModule):
        def step(self, inputs: Inputs) -> None:
            assert inputs.reverse["out"] is None

        def forward_outputs(self) -> Mapping[str, object]:
            return {"out": Signal(active=True)}

        def snapshot(self) -> JsonValue:
            return {}

        def restore(self, state: JsonValue) -> None:
            pass

    class Lamp(Contact):
        lit = False

        def step(self, inputs: Inputs) -> None:
            feed = inputs.forward["feed"]
            assert isinstance(feed, Signal)
            self.lit = feed.active

        def forward_outputs(self) -> Mapping[str, object]:
            return {}

    reg = ModuleRegistry()
    reg.register(
        manifest("test.contact", [{"port": "out", "type": "signal"}], []), Contact, Contact
    )
    reg.register(SENSOR, Lamp, Lamp)
    kernel = Kernel(seed=1)
    plant = reg.build(
        kernel,
        instances=[InstanceSpec("test.contact", "C"), InstanceSpec("test.sensor", "L")],
        connections=[Connection("test.sensor[L].feed", "test.contact[C].out")],
    )
    kernel.run(2)
    assert plant.module("test.sensor", "L").lit is True


# --- quiescence --------------------------------------------------------------
# A module that reports itself quiescent is not stepped until one of its inputs
# changes. That must never change a run, only its cost.


class CountingLoad(Load):
    """A load that is quiescent between input changes and counts its steps."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        super().__init__(ctx, params)
        self.calls = 0

    def quiescent(self) -> bool:
        return True

    def step(self, inputs: Inputs) -> None:
        self.calls += 1
        feed = inputs.forward["feed"]
        assert isinstance(feed, ElectricalSupply)
        self.draw = self.kw if feed.energized else 0.0


class RestlessLoad(CountingLoad):
    def quiescent(self) -> bool:
        return False


def quiet_plant(load: type[SimModule], on_at: int) -> tuple[Kernel, Any]:
    reg = ModuleRegistry()
    reg.register(SOURCE, Source, Source)
    reg.register(LOAD, load, load)
    kernel = Kernel(seed=3)
    plant = reg.build(
        kernel,
        instances=[
            InstanceSpec("test.source", "S1", params={"on_at_step": on_at}),
            InstanceSpec("test.load", "L1", params={"kw": 100.0}),
        ],
        connections=[Connection("test.load[L1].feed", "test.source[S1].out")],
    )
    return kernel, plant


def test_quiescent_module_is_stepped_only_when_an_input_changes() -> None:
    kernel, plant = quiet_plant(CountingLoad, on_at=5)
    kernel.run(20)
    load = plant.module("test.load", "L1")
    # Once at the start, and once when the source comes alive.
    assert load.calls == 2
    assert load.draw == 100.0


def test_quiescence_does_not_change_the_run() -> None:
    def run(load: type[SimModule]) -> list[tuple[float, list[float]]]:
        kernel, plant = quiet_plant(load, on_at=5)
        out = []
        for _ in range(20):
            kernel.step()
            out.append(
                (
                    plant.module("test.load", "L1").draw,
                    list(plant.module("test.source", "S1").seen_kw),
                )
            )
        return out

    assert run(CountingLoad) == run(RestlessLoad)


def test_slow_step_still_runs_every_second_for_a_quiescent_module() -> None:
    calls: list[int] = []

    class SlowQuiet(CountingLoad):
        def step_slow(self, inputs: Inputs) -> None:
            calls.append(self.ctx.now_ms)

    kernel, _ = quiet_plant(SlowQuiet, on_at=0)
    kernel.run(25)
    assert calls == [0, 1000, 2000]


def test_quiescent_plant_restores_and_continues_identically() -> None:
    kernel, _ = quiet_plant(CountingLoad, on_at=7)
    kernel.run(4)
    saved = kernel.snapshot()
    expected = [(kernel.step(), kernel.state_hash())[1] for _ in range(10)]
    kernel.restore(saved)
    assert [(kernel.step(), kernel.state_hash())[1] for _ in range(10)] == expected


def test_module_changed_from_outside_a_step_wakes_and_is_rehashed() -> None:
    """A fault or a command changes a module between steps; `ctx.wake()` makes it count."""

    class Trippable(CountingLoad):
        def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
            super().__init__(ctx, params)
            self.tripped = False

        def trip(self) -> None:
            self.tripped = True
            self.ctx.wake()

        def step(self, inputs: Inputs) -> None:
            super().step(inputs)
            if self.tripped:
                self.draw = 0.0

        def snapshot(self) -> JsonValue:
            return {"draw": self.draw, "tripped": self.tripped, "seen": []}

    kernel, plant = quiet_plant(Trippable, on_at=0)
    kernel.run(5)
    load = plant.module("test.load", "L1")
    calls, before = load.calls, kernel.state_hash()
    load.trip()
    assert kernel.state_hash() != before
    kernel.step()
    assert load.calls == calls + 1
    assert load.draw == 0.0


# --- settled slow modules ------------------------------------------------------
# A module whose one-second model has reached steady state may say so. The plant
# then skips its slow step until an input changes or it is woken.


class Tank(SimModule):
    """Fills toward its inflow level once a second; settled when the level stops moving."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        super().__init__(ctx, params)
        self.level = 0.0
        self.slow_steps = 0
        self.moving = True
        self.filled = LazyIntegral()

    def step_slow(self, inputs: Inputs) -> None:
        feed = inputs.forward["feed"]
        assert isinstance(feed, ElectricalSupply)
        target = 10.0 if feed.energized else 0.0
        change = round((target - self.level) / 2.0, 3)
        self.level += change
        self.moving = change != 0.0
        self.slow_steps += 1
        self.filled.set_rate(self.level, self.ctx.now_ms)

    def step(self, inputs: Inputs) -> None:
        pass

    def quiescent(self) -> bool:
        return True

    def settled(self) -> bool:
        return not self.moving

    def forward_outputs(self) -> Mapping[str, object]:
        return {}

    def reverse_outputs(self) -> Mapping[str, object]:
        return {"feed": ElectricalDemand(kw=self.level)}

    def snapshot(self) -> JsonValue:
        return {"level": self.level, "moving": self.moving, "filled": self.filled.snapshot()}

    def restore(self, state: JsonValue) -> None:
        assert isinstance(state, dict)
        self.level, self.moving = state["level"], state["moving"]  # type: ignore[assignment]
        self.filled.restore(state["filled"])


def tank_plant(on_at: int) -> tuple[Kernel, Any]:
    reg = ModuleRegistry()
    reg.register(SOURCE, Source, Source)
    reg.register(LOAD, Tank, Tank)
    kernel = Kernel(seed=3)
    plant = reg.build(
        kernel,
        instances=[
            InstanceSpec("test.source", "S1", params={"on_at_step": on_at}),
            InstanceSpec("test.load", "L1"),
        ],
        connections=[Connection("test.load[L1].feed", "test.source[S1].out")],
    )
    return kernel, plant


def test_settled_module_is_not_stepped_until_an_input_changes() -> None:
    kernel, plant = tank_plant(on_at=0)
    kernel.run_for(60_000)
    tank = plant.module("test.load", "L1")
    assert tank.level == pytest.approx(10.0, abs=0.01)
    steps = tank.slow_steps
    assert steps < 30, "it stopped stepping once the level stopped moving"
    kernel.run_for(600_000)
    assert tank.slow_steps == steps


def test_input_change_between_slow_ticks_wakes_a_settled_module_at_the_next_one() -> None:
    kernel, plant = tank_plant(on_at=1205)  # the source comes alive mid-second, late in the run
    kernel.run_for(100_000)
    tank = plant.module("test.load", "L1")
    assert tank.level == 0.0 and tank.slow_steps < 5
    kernel.run_for(100_000)
    assert tank.level == pytest.approx(10.0, abs=0.01)


def test_integral_keeps_counting_while_its_module_is_skipped() -> None:
    kernel, plant = tank_plant(on_at=0)
    kernel.run_for(3_600_000)
    tank = plant.module("test.load", "L1")
    # Level 10 for almost the whole hour: about 10 unit-hours.
    assert tank.filled.at(kernel.clock.now_ms) == pytest.approx(10.0, rel=0.01)


def test_pending_wake_survives_snapshot_and_restore() -> None:
    kernel, plant = tank_plant(on_at=1205)
    kernel.run_for(120_600)  # the input changed 100 ms ago; the slow tick has not come yet
    saved = kernel.snapshot()
    kernel.run_for(60_000)
    expected = plant.module("test.load", "L1").level
    kernel.restore(saved)
    kernel.run_for(60_000)
    assert plant.module("test.load", "L1").level == expected == pytest.approx(10.0, abs=0.01)


def test_lazy_integral_adds_rate_times_time() -> None:
    integral = LazyIntegral()
    integral.set_rate(100.0, 0)
    assert integral.at(1_800_000) == pytest.approx(50.0)
    integral.set_rate(0.0, 1_800_000)
    assert integral.at(3_600_000) == pytest.approx(50.0)
    integral.set_rate(20.0, 3_600_000)
    again = LazyIntegral()
    again.restore(integral.snapshot())
    assert again.at(7_200_000) == integral.at(7_200_000) == pytest.approx(70.0)
