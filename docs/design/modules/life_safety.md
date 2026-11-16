# Module spec: `life_safety`

Fire and life safety. Fidelity `F1`. Zone `Z0-PROT`. Instances: one, for example `LS`; keys `pods`.

## Purpose

Air-sampling detection per POD, the fire alarm panel, the hardwired cause-and-effect matrix, emergency power off and the fire pump. Everything here is discrete, and nothing here can be written through any network path.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `pod_fire` per `pods` | provides | `signal` |
| `pod_epo` per `pods` | provides | `signal` |
| `fire_pump_start_request` | provides | `signal` |
| `power` | requires | `electrical` |

## Equations

None: the module is a set of latches. `pod_fire` is the latched confirmed fire of that POD, `pod_epo` its latched emergency power off, and `fire_pump_start_request` is active while the sprinkler main is below pressure. The fire pump draws `fire_pump_kw` while it runs.

## State machine

Detector, per POD: `NORMAL`, `ALERT`, `ACTION`, `FIRE_1`, `FIRE_2`, set by what the detector reads.

Panel:

- `NORMAL`: every detector normal, no fault.
- `PRE_ALARM`: a detector at `ALERT` or `ACTION`.
- `ALARM`: a detector at `FIRE_1` or above, or a confirmed fire not yet reset.
- `FAULT`: a panel fault, or the panel has lost its supply, with every detector normal. Detection and cause and effect continue in this state.

Cause and effect:

- A detector at `FIRE_2` confirms the fire in that POD: its air handlers stop and its dampers close. The latch is released only by a reset at the panel while the detector is below the fire thresholds.
- Emergency power off removes power from one POD and is latched at its station.
- The fire pump is called by a sprinkler pressure drop and runs when it has a supply. It has its own transfer switch and asks for a generator for as long as it is called.

## Points

In `points.yaml`. A point whose name starts with `pod_` exists once per POD, for example `pod_07_smoke_level`. Every point is tier `T0`.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `fire_pump_kw` | 75 | kW | assumed |

## Faults

In `faults.py`. They are events at the equipment: a detector reading, a panel reset, an emergency power off station operated or reset, a panel fault, a sprinkler pressure drop, a fire pump failure.

## Validation cases

- The module contract suite.
- The four thresholds give the panel states above, and only `FIRE_2` stops the air handlers.
- A confirmed fire survives a reset while the detector still reads fire.
- Emergency power off affects one POD and nothing else.
- The fire pump runs on a pressure drop and reports a failure when it is called and cannot run.
- No point is writable.

## Known limits

- No smoke transport: a detector reads what a scenario says it reads.
- Sprinkler zones, the fire water tank and suppression release are not modelled.
- The fire pump's transfer switch is reduced to "runs when its supply is there".
- Nothing consumes `fire_pump_start_request` in the generic profile.
