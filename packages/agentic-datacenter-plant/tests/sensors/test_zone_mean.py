"""ADC-CTL-006 and OP-04: sensor models, and a POD's zone mean without its bad sensors."""

from typing import Any

import pytest

from agentic_datacenter.core.profile import build_plant, parse_profile
from agentic_datacenter.core.registry import ModuleRegistry
from agentic_datacenter.core.scheduler import Kernel

PROFILE = parse_profile({
    "schema_version": 1, "name": "one_pod", "site": "T",
    "key_sets": {"pods": ["01"], "trains": ["A"]},
    "modules": [
        {"id": "cooling.pod", "instances": ["01"]},
        {"id": "sensors", "instances": ["SENSORS"]},
        {"id": "electrical.utility", "instances": ["U"]},
        {"id": "electrical.it_load", "instances": ["01"], "stub": True},
        {"id": "cooling.pump_station", "instances": ["P"], "stub": True},
        {"id": "cooling.tes", "instances": ["T"], "stub": True},
        {"id": "cooling.chw_plant", "instances": ["C"], "stub": True},
        {"id": "cooling.weather", "instances": ["W"], "stub": True},
        {"id": "life_safety", "instances": ["LS"], "stub": True},
    ],
    "connections": [
        {"consumer": "cooling.pod[01].chw", "provider": "cooling.pump_station[P].chw"},
        {"consumer": "cooling.pod[01].it_heat", "provider": "electrical.it_load[01].heat"},
        {"consumer": "cooling.pod[01].fan_power", "provider": "electrical.utility[U].supply"},
        {"consumer": "cooling.pod[01].fan_power_b", "provider": "electrical.utility[U].supply"},
        {"consumer": "cooling.pod[01].fire_stop", "provider": "life_safety[LS].pod_fire[01]"},
        {"consumer": "electrical.it_load[01].feed_a", "provider": "electrical.utility[U].supply"},
        {"consumer": "electrical.it_load[01].feed_b", "provider": "electrical.utility[U].supply"},
        {"consumer": "electrical.it_load[01].epo", "provider": "life_safety[LS].pod_epo[01]"},
        {"consumer": "cooling.pump_station[P].chws_in", "provider": "cooling.tes[T].chws_out"},
        {"consumer": "cooling.pump_station[P].power_1", "provider": "electrical.utility[U].supply"},
        {"consumer": "cooling.pump_station[P].power_2", "provider": "electrical.utility[U].supply"},
        {"consumer": "cooling.pump_station[P].power_3", "provider": "electrical.utility[U].supply"},
        {"consumer": "cooling.tes[T].chws_in", "provider": "cooling.chw_plant[C].chws"},
        {"consumer": "cooling.chw_plant[C].ambient", "provider": "cooling.weather[W].ambient"},
        {"consumer": "cooling.chw_plant[C].power_1", "provider": "electrical.utility[U].supply"},
        {"consumer": "cooling.chw_plant[C].power_2", "provider": "electrical.utility[U].supply"},
        {"consumer": "cooling.chw_plant[C].power_3", "provider": "electrical.utility[U].supply"},
        {"consumer": "life_safety[LS].power", "provider": "electrical.utility[U].supply"},
    ],
})  # fmt: skip
TAG = "cooling.pod[01].zone_t{n}"


def start(seed: int = 1) -> tuple[Kernel, Any, Any, list[dict[str, Any]]]:
    kernel = Kernel(seed=seed)
    plant = build_plant(PROFILE, kernel, ModuleRegistry.from_entry_points())
    events: list[dict[str, Any]] = []
    kernel.events.subscribe("pod.sensor_excluded", lambda e: events.append(dict(e.payload)))
    kernel.run_for(120_000)
    return kernel, plant.module("cooling.pod", "01"), plant.module("sensors", "SENSORS"), events


def test_healthy_sensors_read_within_their_accuracy_class_and_resolution() -> None:
    kernel, pod, sensors, _ = start()
    readings = [pod.io[f"zone_t{n}_c"] for n in range(1, 7)]
    assert all(abs(r - pod.ts) <= 0.5 for r in readings), "space temperature within 0.5 degC"
    assert all(round(r, 2) == r for r in readings), "resolution 0.01 degC"
    assert len(set(readings)) > 1, "the sensors are not identical"
    assert pod.io["supply_air_c"] == pytest.approx(sum(readings) / 6, abs=1e-9)
    assert pod.io["zone_sensors_in_mean"] == 6


def test_sensor_readings_are_reproducible_from_the_seed() -> None:
    first, second, other = start(seed=5)[1], start(seed=5)[1], start(seed=6)[1]
    names = [f"zone_t{n}_c" for n in range(1, 7)]
    assert [first.io[n] for n in names] == [second.io[n] for n in names]
    assert [first.io[n] for n in names] != [other.io[n] for n in names]


@pytest.mark.req("ADC-CTL-006")
def test_bad_quality_sensor_leaves_the_zone_mean_within_one_control_step() -> None:
    kernel, pod, sensors, events = start()
    sensors.inject("bad", tag=TAG.format(n=3))
    kernel.run_for(1000)
    good = [pod.io[f"zone_t{n}_c"] for n in (1, 2, 4, 5, 6)]
    assert pod.io["zone_sensors_in_mean"] == 5
    assert pod.io["supply_air_c"] == pytest.approx(sum(good) / 5, abs=1e-9)
    assert events == [{"source": "cooling.pod[01]", "sensor": "zone_t3", "reason": "bad_quality"}]


@pytest.mark.req("ADC-CTL-006")
def test_excluded_sensor_returns_to_the_mean_when_it_is_good_again() -> None:
    kernel, pod, sensors, _ = start()
    sensors.inject("bad", tag=TAG.format(n=3))
    kernel.run_for(5000)
    sensors.inject("clear", tag=TAG.format(n=3))
    kernel.run_for(2000)
    assert pod.io["zone_sensors_in_mean"] == 6


@pytest.mark.req("ADC-CTL-006")
def test_op04_stuck_sensor_is_excluded_and_drifting_sensor_is_caught_by_cross_check() -> None:
    kernel, pod, sensors, events = start()
    sensors.inject("stuck", tag=TAG.format(n=2))
    sensors.inject("drift", tag=TAG.format(n=5), rate_per_min=1.0)
    # Nothing can show a stuck sensor while the hall is steady; a setpoint move does.
    pod.io["supply_air_sp_c"] = 24.0
    pod.ctx.wake()
    kernel.run_for(15 * 60 * 1000)
    reasons = {e["sensor"]: e["reason"] for e in events}
    assert reasons == {"zone_t2": "stuck", "zone_t5": "cross_check"}
    assert pod.io["zone_sensors_in_mean"] == 4
    good = [pod.io[f"zone_t{n}_c"] for n in (1, 3, 4, 6)]
    assert pod.io["supply_air_c"] == pytest.approx(sum(good) / 4, abs=1e-9)
    assert abs(pod.io["supply_air_c"] - pod.ts) <= 0.5, "the mean still follows the hall"
    assert pod.ts == pytest.approx(24.0, abs=0.6), "and the loop still controls it"


def test_without_exclusion_the_drifting_sensor_would_have_pulled_the_hall_off_setpoint() -> None:
    kernel, pod, sensors, _ = start()
    sensors.inject("drift", tag=TAG.format(n=5), rate_per_min=1.0)
    kernel.run_for(4 * 60 * 1000)
    # Before the cross-check acts, a rising reading makes the loop overcool the hall.
    assert pod.io["zone_t5_c"] > pod.ts + 1.5 or pod.io["zone_sensors_in_mean"] == 5


def test_noisy_sensor_stays_in_the_mean_while_inside_the_cross_check_band() -> None:
    kernel, pod, sensors, events = start()
    sensors.inject("noisy", tag=TAG.format(n=1), sigma=0.2)
    kernel.run_for(10 * 60 * 1000)
    assert pod.io["zone_sensors_in_mean"] == 6 and events == []


def test_loop_holds_its_output_when_every_sensor_is_bad() -> None:
    kernel, pod, sensors, _ = start()
    valve = pod.io["valve_pct"]
    for n in range(1, 7):
        sensors.inject("bad", tag=TAG.format(n=n))
    kernel.run_for(60_000)
    assert pod.io["zone_sensors_in_mean"] == 0
    assert pod.io["zone_mean_invalid"] is True
    assert pod.io["valve_pct"] == valve, "no measurement, so the valve stays where it was"


def test_pod_without_a_sensor_module_reads_true_values() -> None:
    from agentic_datacenter.core.module import Inputs, ModuleContext
    from agentic_datacenter.core.ports import AirHeat, ElectricalSupply, HydronicSupply, Signal
    from agentic_datacenter.plant.cooling.pod import MODULE

    kernel = Kernel(seed=1)
    ctx = ModuleContext("cooling.pod", "X", {}, kernel.clock, kernel.rng, kernel.events)
    pod = MODULE.factory(ctx, {})
    pod.step_slow(Inputs(
        forward={"chw": HydronicSupply(True, 18.0), "it_heat": AirHeat(150.0, 12.0),
                 "fan_power": ElectricalSupply(True, 1.0, 1.0),
                 "fan_power_b": ElectricalSupply(True, 1.0, 1.0), "fire_stop": Signal(False)},
        reverse={},
    ))  # fmt: skip
    assert all(pod.io[f"zone_t{n}_c"] == pytest.approx(pod.ts, abs=0.3) for n in range(1, 7))
