"""The module contract suite (SDD 5.3).

A plant module must pass this before it is trusted in a plant: its outputs
match its manifest, it is deterministic under a seed, its snapshot captures
everything that affects its behaviour, and its stub offers the same ports.

The module is run alone. Each port it requires is fed a nominal value by a
synthetic source, and each port it provides is loaded by a synthetic sink, so
the check needs no other plant module.
"""

from __future__ import annotations

from collections.abc import Mapping

from agentic_datacenter.core.module import (
    Inputs,
    LatchedModule,
    Manifest,
    ModuleContext,
    ModuleContractError,
    ModuleEntry,
    SimModule,
    parse_manifest,
)
from agentic_datacenter.core.ports import (
    PORT_TYPES,
    AirHeat,
    AirInlet,
    ElectricalDemand,
    ElectricalSupply,
    FuelDemand,
    FuelSupply,
    HydronicReturn,
    HydronicSupply,
    PortType,
    Signal,
    Weather,
)
from agentic_datacenter.core.registry import Connection, InstanceSpec, ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue

NOMINAL_FORWARD: Mapping[str, object] = {
    "electrical": ElectricalSupply(energized=True, voltage_pu=1.0, frequency_pu=1.0),
    "hydronic": HydronicSupply(available=True, supply_c=18.0),
    "air_heat": AirHeat(heat_kw=100.0, airflow_kg_s=10.0),
    "signal": Signal(active=False),
    "fuel": FuelSupply(available=True),
    "weather": Weather(dry_bulb_c=20.0, rel_humidity_pct=50.0),
}
NOMINAL_REVERSE: Mapping[str, object] = {
    "electrical": ElectricalDemand(kw=100.0),
    "hydronic": HydronicReturn(flow_kg_s=5.0, heat_kw=100.0),
    "air_heat": AirInlet(inlet_c=22.0),
    "fuel": FuelDemand(litre_per_h=10.0),
}
CONTRACT_KEYS = ("k1", "k2")
_INSTANCE = "X"


def _manifest(module_id: str, provides: list[str], requires: list[str]) -> Manifest:
    return parse_manifest(
        {
            "id": module_id,
            "version": "0.0.0",
            "fidelity": "F0",
            "provides": [{"port": "out", "type": t} for t in provides],
            "requires": [{"port": "inp", "type": t} for t in requires],
            "zone": "Z-CONTRACT",
            "requirements": [],
            "spec": "docs/design/modules/contract.md",
        }
    )


def _source(ptype: PortType) -> type[SimModule]:
    class Source(LatchedModule):
        def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
            super().__init__(ctx, params)
            self.forward = {"out": NOMINAL_FORWARD[ptype.name]}

        def step(self, inputs: Inputs) -> None:
            pass

    return Source


def _sink(ptype: PortType) -> type[SimModule]:
    class Sink(LatchedModule):
        def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
            super().__init__(ctx, params)
            if ptype.reverse is not None:
                self.reverse = {"inp": NOMINAL_REVERSE[ptype.name]}

        def step(self, inputs: Inputs) -> None:
            pass

    return Sink


def _build(entry: ModuleEntry, seed: int, *, stub: bool) -> Kernel:
    manifest = entry.manifest
    registry = ModuleRegistry()
    registry.register(manifest, entry.factory, entry.stub)
    for ptype in PORT_TYPES.values():
        registry.register(
            _manifest(f"contract.source_{ptype.name}", [ptype.name], []),
            _source(ptype),
            _source(ptype),
        )
        registry.register(
            _manifest(f"contract.sink_{ptype.name}", [], [ptype.name]), _sink(ptype), _sink(ptype)
        )
    target = f"{manifest.id}[{_INSTANCE}]"
    keys = {d.keyed_by: CONTRACT_KEYS for d in manifest.provides if d.keyed_by}
    instances = [InstanceSpec(manifest.id, _INSTANCE, keys=keys, stub=stub)]
    connections = []
    for decl in manifest.requires:
        name = f"src_{decl.port}"
        instances.append(InstanceSpec(f"contract.source_{decl.type}", name))
        connections.append(
            Connection(f"{target}.{decl.port}", f"contract.source_{decl.type}[{name}].out")
        )
    for decl in manifest.provides:
        for key in CONTRACT_KEYS if decl.keyed_by else (None,):
            port = decl.port if key is None else f"{decl.port}[{key}]"
            name = f"sink_{decl.port}" if key is None else f"sink_{decl.port}_{key}"
            instances.append(InstanceSpec(f"contract.sink_{decl.type}", name))
            connections.append(
                Connection(f"contract.sink_{decl.type}[{name}].inp", f"{target}.{port}")
            )
    kernel = Kernel(seed=seed)
    registry.build(kernel, instances, connections)
    return kernel


def _hashes(kernel: Kernel, steps: int) -> list[str]:
    out = []
    for _ in range(steps):
        kernel.step()
        out.append(kernel.state_hash())
    return out


def check_module(entry: ModuleEntry, seed: int = 1, steps: int = 25) -> None:
    """Run the contract suite on one module and its stub.

    Raises:
        ModuleContractError: Naming the first property the module fails.
    """
    name = entry.manifest.id
    for stub in (False, True):
        what = f"{name} (stub)" if stub else name
        if _hashes(_build(entry, seed, stub=stub), steps) != _hashes(
            _build(entry, seed, stub=stub), steps
        ):
            raise ModuleContractError(f"{what} is not deterministic under a seed")
        kernel = _build(entry, seed, stub=stub)
        kernel.run(steps)
        saved = kernel.snapshot()
        expected = _hashes(kernel, steps)
        kernel.restore(saved)
        if _hashes(kernel, steps) != expected:
            raise ModuleContractError(
                f"{what}: its snapshot does not capture everything that affects its behaviour"
            )
