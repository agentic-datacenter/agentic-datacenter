"""Life safety and security at fidelity F1 (SDD 6.4): discrete and hardwired."""

from typing import Any

import pytest

from agentic_datacenter.core.ports import ElectricalSupply
from agentic_datacenter.plant.life_safety import MODULE as LIFE_SAFETY
from agentic_datacenter.plant.security import MODULE as SECURITY

LIVE = ElectricalSupply(True, 1.0, 1.0)
DEAD = ElectricalSupply(False, 0.0, 0.0)
PODS = ("01", "02", "03")


def life_safety(rig: Any) -> Any:
    r = rig(LIFE_SAFETY, {}, keys={"pods": PODS})
    r.forward["power"] = LIVE
    r.run(1)
    return r


def test_modules_are_at_fidelity_one() -> None:
    assert LIFE_SAFETY.manifest.fidelity == "F1" and SECURITY.manifest.fidelity == "F1"


def test_four_escalating_thresholds_and_the_panel_states(rig: Any) -> None:
    r = life_safety(rig)
    io = r.module.io
    assert io["panel_state"] == "NORMAL"
    seen = []
    for level in ("ALERT", "ACTION", "FIRE_1", "FIRE_2"):
        r.module.inject("smoke", pod="02", level=level)
        r.run(1)
        seen.append((io["pod_02_smoke_level"], io["panel_state"], r.out("pod_fire[02]").active))
    assert seen == [
        ("ALERT", "PRE_ALARM", False),
        ("ACTION", "PRE_ALARM", False),
        ("FIRE_1", "ALARM", False),
        ("FIRE_2", "ALARM", True),
    ]
    assert io["alarm_fire"] and io["pod_02_fire_confirmed"]
    assert not r.out("pod_fire[01]").active and not r.out("pod_fire[03]").active
    assert not r.out("pod_epo[02]").active, "a fire does not operate the emergency power off"


def test_confirmed_fire_is_latched_until_the_panel_is_reset_with_the_detector_clear(
    rig: Any,
) -> None:
    r = life_safety(rig)
    r.module.inject("smoke", pod="01", level="FIRE_2")
    r.run(1)
    r.module.inject("panel_reset")
    r.run(1)
    assert r.out("pod_fire[01]").active, "the detector still reads fire"
    r.module.inject("smoke", pod="01", level="NORMAL")
    r.run(1)
    assert r.out("pod_fire[01]").active and r.module.io["panel_state"] == "ALARM"
    r.module.inject("panel_reset")
    r.run(1)
    assert not r.out("pod_fire[01]").active and r.module.io["panel_state"] == "NORMAL"


def test_emergency_power_off_removes_power_from_one_pod_and_is_latched(rig: Any) -> None:
    r = life_safety(rig)
    r.module.inject("epo", pod="03")
    r.run(1)
    assert r.out("pod_epo[03]").active and r.module.io["pod_03_epo_active"]
    assert not r.out("pod_epo[01]").active and not r.out("pod_fire[03]").active
    r.run(600)
    assert r.out("pod_epo[03]").active
    r.module.inject("epo_reset", pod="03")
    r.run(1)
    assert not r.out("pod_epo[03]").active


def test_fire_pump_runs_on_a_sprinkler_pressure_drop(rig: Any) -> None:
    r = life_safety(rig)
    io = r.module.io
    assert not io["fire_pump_running"] and r.back("power").kw == 0.0
    r.module.inject("sprinkler_pressure_drop")
    r.run(1)
    assert io["fire_pump_called"] and io["fire_pump_running"]
    assert r.out("fire_pump_start_request").active and r.back("power").kw == pytest.approx(75.0)
    r.forward["power"] = DEAD
    r.run(1)
    assert not io["fire_pump_running"] and io["alarm_fire_pump_failed"]
    assert r.out("fire_pump_start_request").active, "it keeps asking for a generator"
    r.forward["power"] = LIVE
    r.module.inject("fire_pump_failure")
    r.run(1)
    assert io["alarm_fire_pump_failed"]
    r.module.inject("fire_pump_restore")
    r.module.inject("sprinkler_pressure_restore")
    r.run(1)
    assert not io["fire_pump_called"] and not r.out("fire_pump_start_request").active


def test_panel_fault_and_loss_of_supply_show_as_fault_but_detection_goes_on(rig: Any) -> None:
    r = life_safety(rig)
    io = r.module.io
    r.module.inject("panel_fault")
    r.run(1)
    assert io["panel_state"] == "FAULT" and io["alarm_panel_fault"]
    r.module.inject("panel_fault_clear")
    r.forward["power"] = DEAD
    r.run(1)
    assert io["panel_state"] == "FAULT"
    r.module.inject("smoke", pod="01", level="FIRE_2")
    r.run(1)
    assert io["panel_state"] == "ALARM" and r.out("pod_fire[01]").active


def test_no_life_safety_or_security_point_can_be_written(rig: Any) -> None:
    for entry, keys in ((LIFE_SAFETY, {"pods": PODS}), (SECURITY, {})):
        board = rig(entry, {}, keys=keys).module.io
        assert {board.declaration(name).tier for name in board} == {"T0"}
        assert not [name for name in board if board.declaration(name).kind.endswith("_cmd")]


def test_bad_events_are_refused(rig: Any) -> None:
    r = life_safety(rig)
    with pytest.raises(ValueError, match="pod"):
        r.module.inject("smoke", pod="99", level="ALERT")
    with pytest.raises(ValueError, match="level"):
        r.module.inject("smoke", pod="01", level="LOTS")


def test_security_events_are_counted_published_and_latched(rig: Any) -> None:
    r = rig(SECURITY, {})
    heard: list[Any] = []
    r.kernel.events.subscribe("security.event", heard.append)
    io = r.module.io
    for kind, where in (
        ("granted", "DOOR-MAIN"),
        ("denied", "DOOR-POD-07"),
        ("forced", "DOOR-EPOD-A"),
        ("held", "DOOR-MAIN"),
        ("intrusion", "PERIMETER-NORTH"),
        ("denied", "DOOR-POD-07"),
    ):
        r.module.inject("event", kind=kind, where=where)
    r.run(1)
    counted = {kind: io[f"events_{kind}"] for kind in ("granted", "denied", "forced", "held")}
    assert counted == {"granted": 1, "denied": 2, "forced": 1, "held": 1}
    assert io["alarm_door_forced"] and io["alarm_door_held"] and io["alarm_intrusion"]
    assert len(heard) == 6
    r.module.inject("clear", kind="forced")
    assert not io["alarm_door_forced"] and io["alarm_intrusion"]
    with pytest.raises(ValueError, match="kind"):
        r.module.inject("event", kind="opened-by-agentic-datacenter", where="x")
    with pytest.raises(ValueError, match="kind"):
        r.module.inject("clear", kind="granted")
