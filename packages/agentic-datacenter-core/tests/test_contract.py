"""The module contract suite an extension must pass before it loads (SDD 5.3)."""

from collections.abc import Mapping

import pytest

from agentic_datacenter.core.contract import check_module
from agentic_datacenter.core.module import (
    Inputs,
    ModuleContext,
    ModuleContractError,
    ModuleEntry,
    SimModule,
    parse_manifest,
)
from agentic_datacenter.core.ports import ElectricalDemand, ElectricalSupply, Signal
from agentic_datacenter.core.state import JsonValue

MANIFEST = parse_manifest(
    {
        "id": "test.relay",
        "version": "0.1.0",
        "fidelity": "F0",
        "provides": [
            {"port": "bus", "type": "electrical"},
            {"port": "alarm", "type": "signal", "keyed_by": "zones"},
        ],
        "requires": [{"port": "feed", "type": "electrical"}],
        "zone": "Z-TEST",
        "requirements": ["ADC-MOD-004"],
        "spec": "docs/design/modules/test.relay.md",
    }
)


class Relay(SimModule):
    """Passes its feed on and counts steps; well behaved."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        super().__init__(ctx, params)
        self.steps = 0
        self.feed = ElectricalSupply(False, 0.0, 0.0)
        self.demand = 0.0

    def step(self, inputs: Inputs) -> None:
        feed, demand = inputs.forward["feed"], inputs.reverse["bus"]
        assert isinstance(feed, ElectricalSupply) and isinstance(demand, ElectricalDemand)
        self.feed, self.demand = feed, demand.kw
        self.steps += 1

    def forward_outputs(self) -> Mapping[str, object]:
        alarms = {f"alarm[{z}]": Signal(False) for z in self.ctx.keys["zones"]}
        return {"bus": self.feed, **alarms}

    def reverse_outputs(self) -> Mapping[str, object]:
        return {"feed": ElectricalDemand(self.demand)}

    def snapshot(self) -> JsonValue:
        return {
            "steps": self.steps,
            "demand": self.demand,
            "feed": [self.feed.energized, self.feed.voltage_pu, self.feed.frequency_pu],
        }

    def restore(self, state: JsonValue) -> None:
        assert isinstance(state, dict)
        feed = state["feed"]
        assert isinstance(feed, list)
        self.steps = state["steps"]  # type: ignore[assignment]
        self.demand = state["demand"]  # type: ignore[assignment]
        self.feed = ElectricalSupply(*feed)  # type: ignore[arg-type]


class ForgetsState(Relay):
    """Leaves the step counter out of its snapshot."""

    def snapshot(self) -> JsonValue:
        return {"demand": self.demand, "feed": [False, 0.0, 0.0]}

    def restore(self, state: JsonValue) -> None:
        pass

    def forward_outputs(self) -> Mapping[str, object]:
        out = dict(super().forward_outputs())
        out["bus"] = ElectricalSupply(self.steps % 7 == 0, 1.0, 1.0)
        return out


class Unseeded(Relay):
    """Behaves differently in each run of the same seed."""

    runs = 0

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        super().__init__(ctx, params)
        type(self).runs += 1
        self.offset = type(self).runs

    def snapshot(self) -> JsonValue:
        return {"offset": self.offset, "steps": self.steps}


class StubWithoutAlarm(Relay):
    """A stub that does not offer the same ports."""

    def forward_outputs(self) -> Mapping[str, object]:
        return {"bus": self.feed}


@pytest.mark.req("ADC-MOD-004")
def test_well_behaved_module_passes() -> None:
    check_module(ModuleEntry(MANIFEST, Relay, Relay))


@pytest.mark.req("ADC-KRN-002")
def test_module_whose_snapshot_misses_state_fails() -> None:
    with pytest.raises(ModuleContractError, match="snapshot"):
        check_module(ModuleEntry(MANIFEST, ForgetsState, ForgetsState))


@pytest.mark.req("ADC-KRN-001")
def test_module_that_is_not_deterministic_fails() -> None:
    with pytest.raises(ModuleContractError, match="determinis"):
        check_module(ModuleEntry(MANIFEST, Unseeded, Relay))


@pytest.mark.req("ADC-MOD-004")
def test_stub_with_other_ports_fails() -> None:
    with pytest.raises(ModuleContractError, match="alarm"):
        check_module(ModuleEntry(MANIFEST, Relay, StubWithoutAlarm))
