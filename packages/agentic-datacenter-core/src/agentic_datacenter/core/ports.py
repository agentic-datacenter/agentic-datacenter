"""Typed ports: the only way plant modules exchange values.

A connection joins one *required* port of a consumer to one *provided* port of
a provider. It carries a forward value from provider to consumer (the state of
a bus, the supply temperature of a loop) and, for most types, a reverse value
from consumer to provider (the power drawn, the heat returned).

Reverse values are additive wherever one provider can feed several consumers,
so what the provider sees is the plain sum of what its consumers report. That
makes conservation a property of the port type and not of each module.
"""

from __future__ import annotations

import dataclasses
import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from agentic_datacenter.core.state import JsonValue


@dataclass(frozen=True)
class ElectricalSupply:
    """State of the bus a consumer is fed from, in per-unit of nominal."""

    energized: bool
    voltage_pu: float
    frequency_pu: float


@dataclass(frozen=True)
class ElectricalDemand:
    """Real power drawn from a bus."""

    kw: float


@dataclass(frozen=True)
class HydronicSupply:
    """Water offered to a consumer."""

    available: bool
    supply_c: float


@dataclass(frozen=True)
class HydronicReturn:
    """Flow taken by a consumer and heat added to it."""

    flow_kg_s: float
    heat_kw: float


@dataclass(frozen=True)
class AirHeat:
    """Heat released into an air stream, and the airflow that carries it."""

    heat_kw: float
    airflow_kg_s: float


@dataclass(frozen=True)
class AirInlet:
    """Temperature of the air returned to the heat source's inlet."""

    inlet_c: float


@dataclass(frozen=True)
class Signal:
    """A hardwired contact."""

    active: bool


@dataclass(frozen=True)
class FuelSupply:
    """Whether fuel can be drawn."""

    available: bool


@dataclass(frozen=True)
class FuelDemand:
    """Fuel drawn."""

    litre_per_h: float


@dataclass(frozen=True)
class Weather:
    """Outdoor conditions."""

    dry_bulb_c: float
    rel_humidity_pct: float


@dataclass(frozen=True)
class PortType:
    """One kind of connection.

    Attributes:
        name: Name used in manifests.
        forward: Class of the value a provider gives its consumers.
        reverse: Class of the value a consumer gives back, or None.
        single_consumer: True when the reverse value cannot be added up, so the
            provided port accepts one consumer only.
    """

    name: str
    forward: type
    reverse: type | None = None
    single_consumer: bool = False


PORT_TYPES: Mapping[str, PortType] = {
    t.name: t
    for t in (
        PortType("electrical", ElectricalSupply, ElectricalDemand),
        PortType("hydronic", HydronicSupply, HydronicReturn),
        PortType("air_heat", AirHeat, AirInlet, single_consumer=True),
        PortType("signal", Signal),
        PortType("fuel", FuelSupply, FuelDemand),
        PortType("weather", Weather),
    )
}


#: Resolution at which slowly converging models report a port value.
REPORT_DIGITS = 4


def settled(value: float) -> float:
    """Round a port value to the reporting resolution (0.1 W, 0.1 mK, 0.1 g/s).

    A thermal model approaches its steady state without ever arriving, so the
    values it reports would change in the twelfth digit every second for ever,
    and every module downstream would be stepped for it. Reporting at a fixed
    resolution lets a plant that is in steady state come to rest. The module
    keeps its own state at full precision; only what crosses a port is rounded.
    """
    return round(value, REPORT_DIGITS)


def port_type(name: str) -> PortType:
    """Return the port type called *name*.

    Raises:
        ValueError: If there is no such type.
    """
    try:
        return PORT_TYPES[name]
    except KeyError:
        known = ", ".join(sorted(PORT_TYPES))
        raise ValueError(f"unknown port type {name!r}; known types: {known}") from None


def combine_reverse(ptype: PortType, values: Sequence[object]) -> object | None:
    """Combine what the consumers of one provided port report.

    Additive types are summed field by field with an order-independent sum, so
    the result does not depend on the order of the consumers. With no consumer
    the result is zero demand.

    Returns:
        The combined reverse value, or None for a type that has none.

    Raises:
        TypeError: If a value is not of the type's reverse class.
        ValueError: If a single-consumer type is given more than one value.
    """
    cls = ptype.reverse
    if cls is None:
        return None
    for value in values:
        if type(value) is not cls:
            raise TypeError(f"{ptype.name} port expects {cls.__name__}, got {type(value).__name__}")
    if ptype.single_consumer:
        if len(values) > 1:
            raise ValueError(f"{ptype.name} port accepts one consumer, got {len(values)}")
        return values[0] if values else None
    fields = [f.name for f in dataclasses.fields(cls)]
    summed: object = cls(**{name: math.fsum(getattr(v, name) for v in values) for name in fields})
    return summed


def value_to_json(value: object) -> dict[str, JsonValue]:
    """Return a port value as a JSON-domain mapping."""
    if not dataclasses.is_dataclass(value) or isinstance(value, type):
        raise TypeError(f"not a port value: {type(value).__name__}")
    return dataclasses.asdict(value)


def value_from_json[T](cls: type[T], data: JsonValue) -> T:
    """Rebuild a port value of class *cls* from :func:`value_to_json` output.

    Raises:
        ValueError: If a field is missing or an unknown one is present.
    """
    if not isinstance(data, Mapping):
        raise ValueError(f"{cls.__name__} must be restored from a mapping")
    names = {f.name for f in dataclasses.fields(cls)}  # type: ignore[arg-type]
    missing, extra = sorted(names - data.keys()), sorted(data.keys() - names)
    if missing or extra:
        raise ValueError(f"{cls.__name__}: missing field(s) {missing}, unknown field(s) {extra}")
    return cls(**data)
