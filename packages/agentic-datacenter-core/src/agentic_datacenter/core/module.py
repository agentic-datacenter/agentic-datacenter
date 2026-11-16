"""The plant module API: manifest, context and the base class.

A module is one plant subsystem. It declares its ports in a manifest and meets
the rest of the plant only through them (ADC-MOD-002). What a module reads in
a step is what the other modules produced in the previous step, so the order in
which modules run never matters.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Literal, Protocol, runtime_checkable

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from agentic_datacenter.core import ports as _ports
from agentic_datacenter.core.clock import SimClock
from agentic_datacenter.core.events import Event, EventBus
from agentic_datacenter.core.ports import PORT_TYPES, value_from_json, value_to_json
from agentic_datacenter.core.rng import RandomStreams, Stream
from agentic_datacenter.core.state import JsonValue

_NAME = r"[a-z][a-z0-9_]*"
PortName = Annotated[str, Field(pattern=rf"^{_NAME}$")]


def param_number(params: Mapping[str, JsonValue], name: str, default: float) -> float:
    """Return the numeric parameter *name*, or *default* when the profile does not give it.

    Raises:
        ValueError: If the profile gives something that is not a number.
    """
    value = params.get(name, default)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"parameter {name} must be a number, got {value!r}")
    return float(value)


#: How long a controller is down after a warm and a cold reboot (SDD 7.4).
REBOOT_MS = {"warm": 60_000, "cold": 180_000}


class ManifestError(ValueError):
    """A module manifest is missing, unreadable or invalid."""


class ModuleContractError(RuntimeError):
    """A module did something its manifest does not declare."""


class PortDecl(BaseModel):
    """One port of a module."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    port: PortName
    type: str
    keyed_by: PortName | None = None

    @model_validator(mode="after")
    def _known_type(self) -> PortDecl:
        if self.type not in PORT_TYPES:
            raise ValueError(f"unknown port type {self.type!r}")
        return self

    def label(self) -> str:
        """Return ``port:type``, with the key set for a keyed port."""
        keyed = f"[{self.keyed_by}]" if self.keyed_by else ""
        return f"{self.port}{keyed}:{self.type}"


class Manifest(BaseModel):
    """The contents of a ``module.yaml``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: Annotated[str, Field(pattern=rf"^{_NAME}(\.{_NAME})?$")]
    version: Annotated[str, Field(pattern=r"^\d+\.\d+\.\d+$")]
    fidelity: Literal["F0", "F1", "F2", "F3"]
    provides: tuple[PortDecl, ...] = ()
    requires: tuple[PortDecl, ...] = ()
    zone: Annotated[str, Field(min_length=1)]
    requirements: tuple[Annotated[str, Field(pattern=r"^ADC-[A-Z]{2,3}-\d{3}$")], ...]
    spec: Annotated[str, Field(pattern=r"^docs/design/modules/.+\.md$")]
    instances: tuple[str, ...] | None = None

    @model_validator(mode="after")
    def _ports_are_consistent(self) -> Manifest:
        names = [p.port for p in (*self.provides, *self.requires)]
        repeated = sorted({n for n in names if names.count(n) > 1})
        if repeated:
            raise ValueError(f"port name(s) used more than once: {', '.join(repeated)}")
        keyed = [p.port for p in self.requires if p.keyed_by]
        if keyed:
            raise ValueError(f"keyed_by is allowed on provided ports only: {', '.join(keyed)}")
        return self

    def zone_for(self, instance: str) -> str:
        """Return the zone of one instance, filling ``{instance}`` in the pattern."""
        return self.zone.replace("{instance}", instance)


def parse_manifest(data: object) -> Manifest:
    """Validate manifest *data*.

    Raises:
        ManifestError: If the data does not satisfy the manifest schema.
    """
    if not isinstance(data, Mapping):
        raise ManifestError("a manifest must be a mapping")
    try:
        return Manifest.model_validate(dict(data))
    except ValidationError as exc:
        problems = "; ".join(
            f"{'.'.join(str(p) for p in e['loc']) or 'manifest'}: {e['msg']} (got {e['input']!r})"
            for e in exc.errors()
        )
        raise ManifestError(f"invalid manifest: {problems}") from exc


def load_manifest(path: Path) -> Manifest:
    """Read and validate the manifest file at *path*.

    Raises:
        ManifestError: If the file is missing, is not YAML, or is invalid.
    """
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ManifestError(f"cannot read manifest {path}: {exc}") from exc
    try:
        return parse_manifest(data)
    except ManifestError as exc:
        raise ManifestError(f"{path}: {exc}") from exc


@dataclass(frozen=True)
class Inputs:
    """What one module reads in one step.

    Attributes:
        forward: For each required port, the value its provider gave.
        reverse: For each provided port, the combined value of its consumers.
            A keyed port has one entry per key, named ``port[key]``.
    """

    forward: Mapping[str, object]
    reverse: Mapping[str, object | None]


@runtime_checkable
class MeasurementService(Protocol):
    """A module that turns true process values into what a sensor reports.

    A measurement is not a flow between subsystems, so it does not go through a
    port. A plant has at most one such module. The plant hands its ``measure``
    to every other module through :meth:`ModuleContext.measure`, so no module
    imports it (ADR 0008).
    """

    def measure(self, tag: str, true_value: float, kind: str) -> tuple[float, bool]:
        """Return the reading of sensor *tag* and whether its quality is good."""
        ...

    def is_static(self, owner: str) -> bool:
        """Say whether the sensors of instance *owner* change only when the process does."""
        ...


class ModuleContext:
    """The kernel services one module instance may use."""

    def __init__(
        self,
        module_id: str,
        instance: str,
        keys: Mapping[str, tuple[str, ...]],
        clock: SimClock,
        rng: RandomStreams,
        events: EventBus,
    ) -> None:
        """Create the context of instance *instance* of module *module_id*."""
        self.module_id = module_id
        self.instance = instance
        self.keys = keys
        self._clock = clock
        self._rng = rng
        self._events = events
        self._wake: Callable[[], None] = lambda: None
        self.reboot_until_ms = -1
        self._measure: Callable[[str, float, str], tuple[float, bool]] | None = None
        self._static: Callable[[], bool] = lambda: True
        self._wake_other: Callable[[str], None] = lambda name: None

    @property
    def name(self) -> str:
        """``module_id[instance]``."""
        return f"{self.module_id}[{self.instance}]"

    @property
    def now_ms(self) -> int:
        """Simulated time in milliseconds."""
        return self._clock.now_ms

    @property
    def step_ms(self) -> int:
        """Length of the fast step in simulated milliseconds."""
        return self._clock.step_ms

    def controller_running(self) -> bool:
        """Say whether this instance's controller is up, that is, not rebooting."""
        return self._clock.now_ms >= self.reboot_until_ms

    def start_reboot(self, duration_ms: int) -> None:
        """Take this instance's controller down for *duration_ms* of simulated time."""
        self.reboot_until_ms = self._clock.now_ms + duration_ms

    def wake(self) -> None:
        """Say that this instance was changed from outside its own step.

        A fault, a command or an event handler that changes a module's state
        calls this, so the module is stepped in the next step even if it is
        quiescent, and its state is hashed again.
        """
        self._wake()

    def bind_wake(self, wake: Callable[[], None]) -> None:
        """Set what :meth:`wake` does. Called by the plant when it is built."""
        self._wake = wake

    def measure(
        self, name: str, true_value: float, kind: str = "temperature"
    ) -> tuple[float, bool]:
        """Return what the sensor called *name* reports for *true_value*, and its quality.

        With no sensor module in the plant the reading is the true value, good.
        """
        if self._measure is None:
            return true_value, True
        return self._measure(name, true_value, kind)

    def measurements_static(self) -> bool:
        """Say whether this instance's sensors can only change when the process does."""
        return self._static()

    def wake_other(self, name: str) -> None:
        """Wake another instance. Available to a measurement service only."""
        self._wake_other(name)

    def bind_measurement(
        self,
        measure: Callable[[str, float, str], tuple[float, bool]],
        static: Callable[[], bool],
    ) -> None:
        """Connect this instance to the plant's measurement service."""
        self._measure, self._static = measure, static

    def bind_wake_other(self, wake_other: Callable[[str], None]) -> None:
        """Let this instance wake others. Called by the plant for a measurement service."""
        self._wake_other = wake_other

    def rng(self, name: str) -> Stream:
        """Return this instance's random stream called *name*."""
        return self._rng.stream(f"{self.name}.{name}")

    def publish(self, topic: str, payload: Mapping[str, JsonValue] | None = None) -> Event:
        """Publish an event with this instance named as its source."""
        body: dict[str, JsonValue] = {"source": self.name}
        if payload:
            body.update(payload)
        return self._events.publish(topic, body)


class SimModule(ABC):
    """Base class of every plant module and of every stub."""

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create one instance.

        Args:
            ctx: Kernel services for this instance.
            params: The instance's parameters from the profile.
        """
        self.ctx = ctx
        self.params = params

    def step_slow(self, inputs: Inputs) -> None:  # noqa: B027 - optional hook
        """Advance the slow models by one second. Runs before :meth:`step`."""

    @abstractmethod
    def step(self, inputs: Inputs) -> None:
        """Advance control and electrical logic by one fast step."""

    def settled(self) -> bool:
        """Say whether the next slow step would change nothing.

        Return True only when :meth:`step_slow`, given the inputs of the last
        slow step again, would leave the state and the outputs as they are. The
        plant then skips the slow step until an input changes or the module is
        woken. Quantities that keep growing while nothing else changes, such as
        energy totals, belong in a :class:`LazyIntegral`. The default never skips.
        """
        return False

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Apply a fault, a local action or a scenario input to this instance.

        This is how a scenario reaches into a module: a breaker that fails to
        open, a manual reset at the device, a utility disturbance. A module
        lists what it accepts in its ``faults.py`` and module spec.

        Every module accepts ``reboot`` with ``kind`` ``warm`` or ``cold``: its
        controller is down for 60 s or 180 s (SDD 7.4). The process goes on;
        what the controller commands stays where it was.

        Raises:
            ModuleContractError: If the module does not know *fault*.
        """
        if fault != "reboot":
            raise ModuleContractError(f"{self.ctx.name} has no fault or action {fault!r}")
        kind = str(params.get("kind", "warm"))
        if kind not in REBOOT_MS:
            raise ModuleContractError(f"{self.ctx.name}: unknown reboot kind {kind!r}")
        self.ctx.start_reboot(REBOOT_MS[kind])
        self.ctx.publish("controller.reboot", {"kind": kind, "seconds": REBOOT_MS[kind] // 1000})
        self.ctx.wake()

    def quiescent(self) -> bool:
        """Say whether the next fast step would change nothing.

        Return True only when :meth:`step`, given the inputs of the last step
        again, would leave both the state and the outputs as they are and draw
        no random number. The plant then skips the step until an input changes
        or the next slow step is due. The default never skips.
        """
        return False

    @abstractmethod
    def forward_outputs(self) -> Mapping[str, object]:
        """Return the forward value of every provided port."""

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the reverse value of every required port that has one."""
        return {}

    @abstractmethod
    def snapshot(self) -> JsonValue:
        """Return the complete state of this instance."""

    @abstractmethod
    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""


_VALUE_CLASSES: dict[str, type] = {
    cls.__name__: cls
    for ptype in PORT_TYPES.values()
    for cls in (ptype.forward, ptype.reverse)
    if cls is not None
}
assert all(getattr(_ports, name) is cls for name, cls in _VALUE_CLASSES.items())


class LazyIntegral:
    """A quantity that grows at a rate which changes only when its owner is stepped.

    ``set_rate`` is called with the present rate at every step the owner takes.
    Between steps the value is the last total plus rate times elapsed time, so
    it stays right while the owner is skipped. Rates are per hour of simulated
    time: a rate in kW gives a value in kWh.
    """

    def __init__(self) -> None:
        """Start at zero with no rate."""
        self._total = 0.0
        self._rate = 0.0
        self._since_ms = 0

    def at(self, now_ms: int) -> float:
        """Return the value at simulated time *now_ms*."""
        return self._total + self._rate * (now_ms - self._since_ms) / 3_600_000.0

    def set_rate(self, rate: float, now_ms: int) -> None:
        """Bring the total up to *now_ms*, then grow at *rate* from there."""
        self._total, self._rate, self._since_ms = self.at(now_ms), rate, now_ms

    def snapshot(self) -> JsonValue:
        """Return the total, the rate and the time the rate was set."""
        return [self._total, self._rate, self._since_ms]

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, list | tuple) or len(state) != 3:
            raise ValueError("integral snapshot is malformed")
        self._total, self._rate = float(str(state[0])), float(str(state[1]))
        self._since_ms = int(str(state[2]))


class LatchedModule(SimModule):
    """A module whose whole state is the port values it last produced.

    A subclass sets ``self.forward`` and ``self.reverse`` in ``__init__`` and
    again in :meth:`step`. Stubs are built on this: a stub has a fixed,
    documented behaviour and nothing to remember beyond its outputs.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create the instance with no outputs set."""
        super().__init__(ctx, params)
        self.forward: dict[str, object] = {}
        self.reverse: dict[str, object] = {}

    def quiescent(self) -> bool:
        """A latched module is a function of its inputs, so it is always quiescent."""
        return True

    def forward_outputs(self) -> Mapping[str, object]:
        """Return the latched forward values."""
        return self.forward

    def reverse_outputs(self) -> Mapping[str, object]:
        """Return the latched reverse values."""
        return self.reverse

    def snapshot(self) -> JsonValue:
        """Return the latched values."""
        return {
            direction: {
                port: [type(value).__name__, value_to_json(value)] for port, value in values.items()
            }
            for direction, values in (("forward", self.forward), ("reverse", self.reverse))
        }

    def restore(self, state: JsonValue) -> None:
        """Put back latched values returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("latched-module snapshot must be a mapping")
        for direction, values in (("forward", self.forward), ("reverse", self.reverse)):
            saved = state[direction]
            if not isinstance(saved, Mapping):
                raise ValueError("latched-module snapshot is malformed")
            values.clear()
            for port, entry in saved.items():
                if not isinstance(entry, list | tuple) or len(entry) != 2:
                    raise ValueError(f"latched value for {port!r} is malformed")
                name, data = entry
                values[port] = value_from_json(_VALUE_CLASSES[str(name)], data)


@dataclass(frozen=True)
class ModuleEntry:
    """What a module registers: its manifest, its class and its stub."""

    manifest: Manifest
    factory: type[SimModule]
    stub: type[SimModule]

    @classmethod
    def from_package(
        cls, init_file: str, factory: type[SimModule], stub: type[SimModule]
    ) -> ModuleEntry:
        """Build the entry of the module whose ``__init__.py`` is *init_file*."""
        return cls(load_manifest(Path(init_file).parent / "module.yaml"), factory, stub)


ENDPOINT = re.compile(rf"^({_NAME}(?:\.{_NAME})?)\[([^\[\]]+)\]\.({_NAME})(?:\[([^\[\]]+)\])?$")
