"""Typed ports: what a connection carries in each direction."""

import dataclasses

import pytest

from agentic_datacenter.core.ports import (
    PORT_TYPES,
    AirInlet,
    ElectricalDemand,
    ElectricalSupply,
    FuelDemand,
    HydronicReturn,
    Signal,
    combine_reverse,
    port_type,
    value_from_json,
    value_to_json,
)


def test_the_six_port_types_of_the_design_exist() -> None:
    assert set(PORT_TYPES) == {"electrical", "hydronic", "air_heat", "signal", "fuel", "weather"}


def test_unknown_port_type_is_refused() -> None:
    with pytest.raises(ValueError, match="steam"):
        port_type("steam")


def test_port_values_are_immutable() -> None:
    supply = ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0)
    with pytest.raises(dataclasses.FrozenInstanceError):
        supply.energized = False  # type: ignore[misc]


def test_electrical_demand_of_several_consumers_adds_up() -> None:
    total = combine_reverse(
        port_type("electrical"), [ElectricalDemand(kw=150.0), ElectricalDemand(kw=75.5)]
    )
    assert total == ElectricalDemand(kw=225.5)


def test_hydronic_return_adds_flow_and_heat() -> None:
    total = combine_reverse(
        port_type("hydronic"),
        [HydronicReturn(flow_kg_s=2.0, heat_kw=60.0), HydronicReturn(flow_kg_s=1.0, heat_kw=30.0)],
    )
    assert total == HydronicReturn(flow_kg_s=3.0, heat_kw=90.0)


def test_no_consumer_gives_zero_demand() -> None:
    assert combine_reverse(port_type("electrical"), []) == ElectricalDemand(kw=0.0)
    assert combine_reverse(port_type("fuel"), []) == FuelDemand(litre_per_h=0.0)


def test_sum_does_not_depend_on_consumer_order() -> None:
    demands = [ElectricalDemand(kw=k) for k in (0.1, 0.2, 0.3, 1e9, -1e9)]
    forward = combine_reverse(port_type("electrical"), demands)
    backward = combine_reverse(port_type("electrical"), list(reversed(demands)))
    assert forward == backward


def test_port_without_a_reverse_value_combines_to_none() -> None:
    assert combine_reverse(port_type("signal"), []) is None
    assert port_type("signal").reverse is None


def test_air_inlet_comes_from_exactly_one_consumer() -> None:
    air = port_type("air_heat")
    assert air.single_consumer
    assert combine_reverse(air, [AirInlet(inlet_c=24.0)]) == AirInlet(inlet_c=24.0)
    with pytest.raises(ValueError, match="one consumer"):
        combine_reverse(air, [AirInlet(inlet_c=24.0), AirInlet(inlet_c=26.0)])


def test_reverse_value_of_the_wrong_type_is_refused() -> None:
    with pytest.raises(TypeError, match="ElectricalDemand"):
        combine_reverse(port_type("electrical"), [Signal(active=True)])  # type: ignore[list-item]


@pytest.mark.parametrize(
    "value",
    [
        ElectricalSupply(energized=True, voltage_pu=0.97, frequency_pu=1.0),
        HydronicReturn(flow_kg_s=2.5, heat_kw=80.0),
        Signal(active=True),
    ],
)
def test_value_survives_a_json_round_trip(value: object) -> None:
    assert value_from_json(type(value), value_to_json(value)) == value


def test_json_with_a_missing_or_extra_field_is_refused() -> None:
    with pytest.raises(ValueError, match="kw"):
        value_from_json(ElectricalDemand, {})
    with pytest.raises(ValueError, match="extra"):
        value_from_json(ElectricalDemand, {"kw": 1.0, "extra": 2})
