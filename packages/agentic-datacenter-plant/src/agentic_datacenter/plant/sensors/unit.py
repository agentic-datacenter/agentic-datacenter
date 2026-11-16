"""Sensor models: what every measured point passes through."""

from __future__ import annotations

from collections.abc import Mapping

from agentic_datacenter.core.module import Inputs, ModuleContext, SimModule, param_number
from agentic_datacenter.core.state import JsonValue

from .faults import MODES

#: Sensor modes in which the reading can change while the process stands still.
MOVING = frozenset({"drift", "noisy"})


class Sensors(SimModule):
    """Sensor models at fidelity F1 (SDD 6.5).

    A healthy sensor reads the true value plus a fixed offset inside its
    accuracy class, rounded to its resolution. The offset of each sensor is
    drawn once from the run seed, so readings are reproducible. Other modules
    reach this one through :meth:`agentic_datacenter.core.module.ModuleContext.measure`.
    """

    def __init__(self, ctx: ModuleContext, params: Mapping[str, JsonValue]) -> None:
        """Create the sensor models of the profile; sensors appear when first read."""
        super().__init__(ctx, params)
        self.accuracy = {
            "temperature": param_number(params, "temperature_accuracy_c", 0.5),
            "humidity": param_number(params, "humidity_accuracy_pct", 5.0),
        }
        self.digits = int(param_number(params, "resolution_digits", 2.0))
        self.sensors: dict[str, dict[str, JsonValue]] = {}
        #: The sensors of each owner, for the table and size in ``_owned_key``.
        self._owned_key: tuple[int, int] = (0, -1)
        self._owned: dict[str, list[dict[str, JsonValue]]] = {}

    def _sensor(self, tag: str, kind: str) -> dict[str, JsonValue]:
        sensor = self.sensors.get(tag)
        if sensor is None:
            band = self.accuracy.get(kind, 0.0)
            # Half the class width, so two sensors of one class never differ by more than it.
            offset = self.ctx.rng(f"offset.{tag}").uniform(-band / 2.0, band / 2.0)
            sensor = self.sensors[tag] = {
                "offset": offset,
                "mode": "healthy",
                "last": 0.0,
                "amount": 0.0,
                "since_ms": 0,
            }
        return sensor

    def measure(self, tag: str, true_value: float, kind: str) -> tuple[float, bool]:
        """Return the reading of sensor *tag* and whether its quality is good."""
        sensor = self._sensor(tag, kind)
        mode, amount = sensor["mode"], float(str(sensor["amount"]))
        if mode in ("stuck", "bad"):
            return float(str(sensor["last"])), mode != "bad"
        value = true_value + float(str(sensor["offset"]))
        if mode == "drift":
            value += amount * (self.ctx.now_ms - int(str(sensor["since_ms"]))) / 60_000.0
        elif mode == "bias":
            value += amount
        elif mode == "noisy":
            value += self.ctx.rng(f"noise.{tag}").gauss(0.0, amount)
        value = round(value, self.digits)
        sensor["last"] = value
        return value, True

    def is_static(self, owner: str) -> bool:
        """Say whether no sensor of *owner* is drifting or noisy."""
        # The sensors of each owner are found once for each table and size of it:
        # a sensor is only ever added, and a restore replaces the whole table.
        key = (id(self.sensors), len(self.sensors))
        if self._owned_key != key:
            self._owned_key, self._owned = key, {}
        owned = self._owned.get(owner)
        if owned is None:
            prefix = owner + "."
            owned = self._owned[owner] = [
                s for tag, s in self.sensors.items() if tag.startswith(prefix)
            ]
        return not any(s["mode"] in MOVING for s in owned)

    def step(self, inputs: Inputs) -> None:
        """Sensors have no step of their own; they are read by the modules they serve."""

    def quiescent(self) -> bool:
        """Nothing happens here between readings."""
        return True

    def forward_outputs(self) -> Mapping[str, object]:
        """The sensor module has no ports."""
        return {}

    def inject(self, fault: str, **params: JsonValue) -> None:
        """Put one sensor into one of the modes listed in ``faults.py``."""
        if fault not in MODES:
            super().inject(fault, **params)
            return
        tag = str(params["tag"])
        sensor = self._sensor(tag, str(params.get("kind", "temperature")))
        sensor["mode"] = "healthy" if fault == "clear" else fault
        amounts = {"drift": "rate_per_min", "bias": "offset", "noisy": "sigma"}
        sensor["amount"] = float(str(params[amounts[fault]])) if fault in amounts else 0.0
        sensor["since_ms"] = self.ctx.now_ms
        self.ctx.publish("sensor.mode", {"tag": tag, "mode": str(sensor["mode"])})
        self.ctx.wake()
        self.ctx.wake_other(tag.rsplit(".", 1)[0])

    def snapshot(self) -> JsonValue:
        """Return every sensor created so far."""
        return {tag: dict(sensor) for tag, sensor in self.sensors.items()}

    def restore(self, state: JsonValue) -> None:
        """Put back a state returned by :meth:`snapshot`."""
        if not isinstance(state, Mapping):
            raise ValueError("sensor snapshot must be a mapping")
        self.sensors = {str(tag): dict(sensor) for tag, sensor in state.items()}  # type: ignore[arg-type]
        self._owned_key, self._owned = (0, -1), {}
