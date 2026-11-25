"""The module registry and the wiring of a plant.

The registry knows which modules exist. Building a plant takes a list of module
instances and a list of connections, checks that every required port is
connected to a provided port of the same type, and schedules the result on a
kernel. Nothing runs until the wiring is known to be complete.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from importlib.metadata import entry_points
from typing import Any

from agentic_datacenter.core.module import (
    ENDPOINT,
    Inputs,
    Manifest,
    MeasurementService,
    ModuleContext,
    ModuleContractError,
    ModuleEntry,
    SimModule,
)
from agentic_datacenter.core.ports import (
    PortType,
    combine_reverse,
    port_type,
    value_from_json,
    value_to_json,
)
from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.core.state import JsonValue

SLOW_PERIOD_MS = 1000


class WiringError(ValueError):
    """The instances and connections given do not make a complete plant."""


@dataclass(frozen=True)
class InstanceSpec:
    """One instance of a module in a plant.

    Attributes:
        module_id: Id of a registered module.
        instance: Name of this instance, unique within the module.
        params: Parameters handed to the module.
        keys: For each key set a keyed port uses, the keys of this instance.
        stub: Build the module's stub instead of the module.
    """

    module_id: str
    instance: str
    params: Mapping[str, JsonValue] = field(default_factory=dict)
    keys: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    stub: bool = False

    @property
    def name(self) -> str:
        """``module_id[instance]``."""
        return f"{self.module_id}[{self.instance}]"


class _ReadParams(dict[str, JsonValue]):
    """An instance's parameters that record which names the module reads (ADR 0033).

    A name counts as read when the module looks it up by index, by ``get`` or
    by ``in``, or iterates the parameters, as a module that maps any name onto
    its points does.
    """

    def __init__(self, params: Mapping[str, JsonValue]) -> None:
        super().__init__(params)
        self.read: set[str] = set()

    def __getitem__(self, name: str) -> JsonValue:
        self.read.add(name)
        return super().__getitem__(name)

    def get(self, name: str, default: Any = None) -> Any:  # noqa: D102
        self.read.add(name)
        return super().get(name, default)

    def __contains__(self, name: object) -> bool:
        if isinstance(name, str):
            self.read.add(name)
        return super().__contains__(name)

    def _all(self) -> None:
        self.read.update(super().keys())

    def __iter__(self) -> Iterator[str]:
        self._all()
        return super().__iter__()

    def keys(self) -> Any:  # noqa: D102
        self._all()
        return super().keys()

    def values(self) -> Any:  # noqa: D102
        self._all()
        return super().values()

    def items(self) -> Any:  # noqa: D102
        self._all()
        return super().items()


@dataclass(frozen=True)
class Connection:
    """A required port joined to a provided port.

    Both ends are written ``module_id[instance].port``; a keyed provided port
    is written ``module_id[instance].port[key]``.
    """

    consumer: str
    provider: str


@dataclass(frozen=True)
class _Registered:
    manifest: Manifest
    factory: type[SimModule]
    stub: type[SimModule]


@dataclass
class _Instance:
    name: str
    manifest: Manifest
    module: SimModule
    provided: dict[str, PortType]
    required: dict[str, PortType]
    forward_types: dict[str, type] = field(init=False)
    reverse_types: dict[str, type] = field(init=False)

    def __post_init__(self) -> None:
        self.forward_types = {p: t.forward for p, t in self.provided.items()}
        self.reverse_types = {
            p: t.reverse for p, t in self.required.items() if t.reverse is not None
        }


def _parse(endpoint: str) -> tuple[str, str]:
    """Split an endpoint into instance name and port (with key, if any)."""
    match = ENDPOINT.match(endpoint)
    if match is None:
        raise WiringError(f"{endpoint!r} is not an endpoint; expected module_id[instance].port")
    module_id, instance, port, key = match.groups()
    return f"{module_id}[{instance}]", port if key is None else f"{port}[{key}]"


class Plant:
    """Wired module instances, stepped by a kernel.

    Each step, a module is run if one of its inputs changed in the previous
    step, if it does not report itself quiescent, or if its slow step is due.
    Skipping the others never changes a run: a quiescent module with unchanged
    inputs would have produced what it produced before.
    """

    def __init__(
        self,
        kernel: Kernel,
        instances: list[_Instance],
        links: dict[tuple[str, str], tuple[str, str]],
    ) -> None:
        """Use :meth:`ModuleRegistry.build`."""
        self._kernel = kernel
        self._instances = {i.name: i for i in instances}
        self._links = links
        self._consumers: dict[tuple[str, str], list[tuple[str, str]]] = {}
        for consumer in sorted(links):
            self._consumers.setdefault(links[consumer], []).append(consumer)
        self._has_slow = {
            i.name: type(i.module).step_slow is not SimModule.step_slow for i in instances
        }
        self._forward: dict[tuple[str, str], object] = {}
        self._reverse: dict[tuple[str, str], object] = {}
        self._dirty: set[str] = set()
        self._pending: set[str] = set()
        for inst in instances:
            kernel.state.register(f"module.{inst.name}", inst.module, tracked=True)
            kernel.state.register(f"ports.{inst.name}", _Ports(self, inst), tracked=True)
        kernel.state.register("plant.pending", self)
        for inst in instances:
            inst.module.ctx.bind_wake(functools.partial(self._woken, inst.name))
        self._bind_measurement(instances)
        for inst in instances:
            self._collect(inst)
        self._dirty = set(self._instances)
        kernel.add_task("plant", self._step)

    def _bind_measurement(self, instances: list[_Instance]) -> None:
        """Give every module the plant's measurement service, if there is one."""
        services = [i for i in instances if isinstance(i.module, MeasurementService)]
        if not services:
            return
        if len(services) > 1:
            names = ", ".join(i.name for i in services)
            raise WiringError(f"a plant has at most one measurement service, found {names}")
        owner, service = services[0].name, services[0].module
        assert isinstance(service, MeasurementService)
        touch = self._kernel.state.touch

        def measure_for(name: str) -> Callable[[str, float, str], tuple[float, bool]]:
            def measure(point: str, true_value: float, kind: str) -> tuple[float, bool]:
                touch(f"module.{owner}")
                return service.measure(f"{name}.{point}", true_value, kind)

            return measure

        for inst in instances:
            if inst.name != owner:
                inst.module.ctx.bind_measurement(
                    measure_for(inst.name), functools.partial(service.is_static, inst.name)
                )
        services[0].module.ctx.bind_wake_other(self._wake_if_present)

    def _wake_if_present(self, name: str) -> None:
        if name in self._instances:
            self._woken(name)

    def module(self, module_id: str, instance: str) -> SimModule:
        """Return one module instance."""
        return self._instances[f"{module_id}[{instance}]"].module

    def instances(self) -> list[tuple[str, Manifest, SimModule]]:
        """Return every instance as (name, manifest, module), sorted by name."""
        return [(i.name, i.manifest, i.module) for i in self._instances.values()]

    def wiring(self) -> list[tuple[str, str, str]]:
        """Return every connection as (consumer, provider, port type), sorted."""
        return [
            (
                f"{consumer[0]}.{consumer[1]}",
                f"{provider[0]}.{provider[1]}",
                self._instances[consumer[0]].required[consumer[1]].name,
            )
            for consumer, provider in sorted(self._links.items())
        ]

    def port_values(self) -> dict[str, dict[str, JsonValue]]:
        """Return every port value carried to the next step, by direction and port."""
        return {
            "forward": {f"{n}.{p}": value_to_json(v) for (n, p), v in self._forward.items()},
            "reverse": {f"{n}.{p}": value_to_json(v) for (n, p), v in self._reverse.items()},
        }

    def _woken(self, name: str) -> None:
        self._dirty.add(name)
        self._kernel.state.touch(f"module.{name}")

    def _inputs(self, inst: _Instance) -> Inputs:
        forward = {port: self._forward[self._links[(inst.name, port)]] for port in inst.required}
        reverse = {
            port: None
            if ptype.reverse is None
            else combine_reverse(
                ptype, [self._reverse[c] for c in self._consumers.get((inst.name, port), ())]
            )
            for port, ptype in inst.provided.items()
        }
        return Inputs(forward=forward, reverse=reverse)

    def _step(self) -> None:
        slow = self._kernel.clock.now_ms % SLOW_PERIOD_MS == 0
        dirty, has_slow, pending = self._dirty, self._has_slow, self._pending
        # An input change reaches a slow model at its next one-second step, so
        # it is remembered until then.
        pending.update(name for name in dirty if has_slow[name])
        due, slow_due = [], set()
        now = self._kernel.clock.now_ms
        for name, inst in self._instances.items():
            # A module whose controller is rebooting is stepped throughout, and
            # once more when the controller is back, so it can act on what it missed.
            rebooting = now <= inst.module.ctx.reboot_until_ms
            if rebooting and has_slow[name]:
                pending.add(name)
            run_slow = slow and has_slow[name] and (name in pending or not inst.module.settled())
            if run_slow:
                slow_due.add(name)
            if run_slow or rebooting or name in dirty or not inst.module.quiescent():
                due.append(inst)
        if not due:
            return
        # Every module reads the values of the previous step, so all inputs are
        # gathered before any module runs.
        inputs = [self._inputs(inst) for inst in due]
        self._dirty = set()
        pending -= slow_due
        for inst, given in zip(due, inputs, strict=True):
            if inst.name in slow_due:
                inst.module.step_slow(given)
        for inst, given in zip(due, inputs, strict=True):
            inst.module.step(given)
        touch = self._kernel.state.touch
        for inst in due:
            touch(f"module.{inst.name}")
            self._collect(inst)

    def _collect(self, inst: _Instance) -> None:
        """Take the outputs of one module and mark whoever must see a change."""
        name, changed = inst.name, False
        forward = inst.module.forward_outputs()
        _check(name, "forward", forward, inst.forward_types)
        for port, value in forward.items():
            if self._forward.get((name, port)) != value:
                self._forward[(name, port)] = value
                changed = True
                for consumer, _ in self._consumers.get((name, port), ()):
                    self._dirty.add(consumer)
        reverse = inst.module.reverse_outputs()
        _check(name, "reverse", reverse, inst.reverse_types)
        for port, value in reverse.items():
            if self._reverse.get((name, port)) != value:
                self._reverse[(name, port)] = value
                changed = True
                self._dirty.add(self._links[(name, port)][0])
        if changed:
            self._kernel.state.touch(f"ports.{name}")

    def snapshot(self) -> JsonValue:
        """Return the instances that have an input change still to act on."""
        reboot = {
            name: inst.module.ctx.reboot_until_ms
            for name, inst in self._instances.items()
            if inst.module.ctx.reboot_until_ms >= 0
        }
        return {"dirty": sorted(self._dirty), "pending": sorted(self._pending), "reboot": reboot}

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("pending-change snapshot must be a mapping")
        dirty, pending = state["dirty"], state["pending"]
        if not isinstance(dirty, list | tuple) or not isinstance(pending, list | tuple):
            raise ValueError("pending-change snapshot is malformed")
        names = {str(n) for n in dirty} | {str(n) for n in pending}
        if not names <= self._instances.keys():
            raise ValueError("pending-change snapshot does not match this plant")
        self._dirty, self._pending = {str(n) for n in dirty}, {str(n) for n in pending}
        reboot = state.get("reboot", {})
        if not isinstance(reboot, Mapping):
            raise ValueError("pending-change snapshot is malformed")
        for name, inst in self._instances.items():
            inst.module.ctx.reboot_until_ms = int(str(reboot.get(name, -1)))


class _Ports:
    """The port values one instance produced, as a part of the simulator state."""

    def __init__(self, plant: Plant, inst: _Instance) -> None:
        self._plant = plant
        self._inst = inst

    def _stores(self) -> list[tuple[str, dict[tuple[str, str], object], dict[str, type]]]:
        inst = self._inst
        reverse = {p: t.reverse for p, t in inst.required.items() if t.reverse is not None}
        return [
            ("forward", self._plant._forward, {p: t.forward for p, t in inst.provided.items()}),
            ("reverse", self._plant._reverse, reverse),
        ]

    def snapshot(self) -> JsonValue:
        name = self._inst.name
        return {
            direction: {port: value_to_json(store[(name, port)]) for port in sorted(classes)}
            for direction, store, classes in self._stores()
        }

    def restore(self, state: JsonValue) -> None:
        if not isinstance(state, Mapping):
            raise ValueError("port snapshot must be a mapping")
        name = self._inst.name
        for direction, store, classes in self._stores():
            saved = state[direction]
            if not isinstance(saved, Mapping) or saved.keys() != classes.keys():
                raise ValueError(f"port snapshot does not match {name} ({direction})")
            for port, cls in classes.items():
                store[(name, port)] = value_from_json(cls, saved[port])


def _check(name: str, direction: str, got: Mapping[str, object], want: Mapping[str, type]) -> None:
    if got.keys() != want.keys():
        missing, extra = sorted(want.keys() - got.keys()), sorted(got.keys() - want.keys())
        raise ModuleContractError(
            f"{name}: {direction} outputs do not match the manifest "
            f"(missing {missing}, undeclared {extra})"
        )
    for port, value in got.items():
        if type(value) is not want[port]:
            raise ModuleContractError(
                f"{name}.{port}: {direction} value must be {want[port].__name__}, "
                f"got {type(value).__name__}"
            )


class ModuleRegistry:
    """The modules a plant can be built from."""

    def __init__(self) -> None:
        """Create an empty registry."""
        self._modules: dict[str, _Registered] = {}
        #: The parameter names each instance's module read in the last build, given
        #: or not: what a facility leaves to a module's defaults (ADR 0033).
        self.reads: dict[str, frozenset[str]] = {}

    def register(self, manifest: Manifest, factory: type[SimModule], stub: type[SimModule]) -> None:
        """Add a module with its manifest and its stub.

        Raises:
            ValueError: If a module with the same id is already registered.
        """
        if manifest.id in self._modules:
            raise ValueError(f"module {manifest.id!r} is already registered")
        self._modules[manifest.id] = _Registered(manifest, factory, stub)

    @classmethod
    def from_entry_points(cls, group: str = "agentic_datacenter.modules") -> ModuleRegistry:
        """Build a registry from every module installed under *group* (SDD 5.3).

        Raises:
            ModuleContractError: If an entry point does not name a ModuleEntry.
        """
        registry = cls()
        for point in sorted(entry_points(group=group), key=lambda p: p.name):
            entry = point.load()
            if not isinstance(entry, ModuleEntry):
                raise ModuleContractError(
                    f"entry point {point.name!r} in {group!r} is not a ModuleEntry"
                )
            registry.register(entry.manifest, entry.factory, entry.stub)
        return registry

    def entries(self) -> list[ModuleEntry]:
        """Return every registered module, sorted by id."""
        return [
            ModuleEntry(r.manifest, r.factory, r.stub) for _, r in sorted(self._modules.items())
        ]

    def manifests(self) -> list[Manifest]:
        """Return every registered manifest, sorted by id."""
        return [self._modules[k].manifest for k in sorted(self._modules)]

    def lock_data(self) -> dict[str, list[dict[str, JsonValue]]]:
        """Return the content of ``modules.lock.yaml`` (ADC-MOD-005)."""
        return {
            "modules": [
                {
                    "id": m.id,
                    "version": m.version,
                    "fidelity": m.fidelity,
                    "provides": [p.label() for p in m.provides],
                    "requires": [p.label() for p in m.requires],
                    "requirements": list(m.requirements),
                    "spec": m.spec,
                }
                for m in self.manifests()
            ]
        }

    def build(
        self, kernel: Kernel, instances: Sequence[InstanceSpec], connections: Sequence[Connection]
    ) -> Plant:
        """Wire *instances* with *connections* and schedule them on *kernel*.

        Raises:
            WiringError: If an instance or endpoint is unknown, a required port
                is unconnected or connected twice, or the two ends of a
                connection differ in type.
            ModuleContractError: If a module's outputs do not match its manifest.
        """
        built: dict[str, _Instance] = {}
        for spec in sorted(instances, key=lambda s: (s.module_id, s.instance)):
            if spec.module_id not in self._modules:
                raise WiringError(f"unknown module {spec.module_id!r} for instance {spec.name}")
            if spec.name in built:
                raise WiringError(f"instance {spec.name} is listed more than once")
            reg = self._modules[spec.module_id]
            provided: dict[str, PortType] = {}
            for decl in reg.manifest.provides:
                if decl.keyed_by is None:
                    provided[decl.port] = port_type(decl.type)
                    continue
                if decl.keyed_by not in spec.keys:
                    raise WiringError(
                        f"{spec.name}.{decl.port} is keyed by {decl.keyed_by!r}, "
                        f"and the instance gives no such keys"
                    )
                for key in spec.keys[decl.keyed_by]:
                    provided[f"{decl.port}[{key}]"] = port_type(decl.type)
            required = {d.port: port_type(d.type) for d in reg.manifest.requires}
            ctx = ModuleContext(
                spec.module_id,
                spec.instance,
                dict(spec.keys),
                kernel.clock,
                kernel.rng,
                kernel.events,
            )
            if spec.stub:
                module = reg.stub(ctx, dict(spec.params))
            else:
                params = _ReadParams(spec.params)
                module = reg.factory(ctx, params)
                self.reads[spec.name] = frozenset(params.read)
                unread = sorted(set(spec.params) - params.read)
                if unread:
                    raise WiringError(
                        f"{spec.name}: the module reads no parameter {', '.join(unread)}; "
                        f"it reads {', '.join(sorted(params.read)) or 'none'} (ADR 0033)"
                    )
            built[spec.name] = _Instance(spec.name, reg.manifest, module, provided, required)

        links: dict[tuple[str, str], tuple[str, str]] = {}
        for conn in connections:
            consumer, provider = _parse(conn.consumer), _parse(conn.provider)
            for end, role in ((consumer, "consumer"), (provider, "provider")):
                if end[0] not in built:
                    raise WiringError(f"{role} {end[0]} of a connection is not in the plant")
            if consumer[1] not in built[consumer[0]].required:
                raise WiringError(f"{consumer[0]} has no required port {consumer[1]!r}")
            offered = built[provider[0]].provided
            if provider[1] not in offered:
                keyed = [p for p in offered if p.startswith(f"{provider[1]}[")]
                hint = f"; it is keyed and needs a key, one of {keyed}" if keyed else ""
                raise WiringError(f"{provider[0]} has no provided port {provider[1]!r}{hint}")
            need, have = built[consumer[0]].required[consumer[1]], offered[provider[1]]
            if need is not have:
                raise WiringError(
                    f"{consumer[0]}.{consumer[1]} requires {need.name} "
                    f"but {provider[0]}.{provider[1]} provides {have.name}"
                )
            if consumer in links:
                raise WiringError(f"{consumer[0]}.{consumer[1]} is connected more than once")
            links[consumer] = provider

        for inst in built.values():
            for port in inst.required:
                if (inst.name, port) not in links:
                    raise WiringError(f"{inst.name}.{port} is not connected")
        fan_in: dict[tuple[str, str], int] = {}
        for provider in links.values():
            fan_in[provider] = fan_in.get(provider, 0) + 1
        for provider, count in fan_in.items():
            if count > 1 and built[provider[0]].provided[provider[1]].single_consumer:
                raise WiringError(
                    f"{provider[0]}.{provider[1]} accepts one consumer, {count} are connected"
                )
        return Plant(kernel, list(built.values()), links)
