# Module spec: `fuel`

Fuel oil system. Fidelity `F1`. Zone `Z1-FUEL`. Instances: one, for example `FUEL`; keys `trains`.

## Purpose

Bulk storage, transfer pumps, scheduled polishing and one sub-base tank per generator with its level controller. It answers one question for the rest of the plant: does this generator still have fuel, and for how long.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `supply` per `trains` | provides | `fuel` |
| `power` | requires | `electrical` |

The reverse value of `supply` is the fuel the generator draws, in litres per hour.

## Equations

One-second step. For each sub-base tank, with level `V` in litres, burn `b` and transfer `q` in litres per hour:

`V' = clamp(V - b/3600 + q/3600, 0, V_max)`, and bulk storage loses what the pumps move.

`q` is the transfer rate while the pump runs, limited by the room left in the tank and by what bulk storage holds. Fuel is available to a generator while `V > 0`. Time to empty is `V / (b - q)` while that is positive, and is reported as 1,000 h otherwise.

Polishing circulates bulk fuel and returns it: it draws power and changes no level.

## State machine

Per sub-base tank, the level controller:

- `IDLE` to `FILLING` when the low switch makes (level at or below the low switch).
- `FILLING` to `IDLE` when the high switch makes.
- A pump that is called runs only with power, with `transfer_enable` set, with no interstitial leak, with bulk fuel left and when it has not failed.
- Independently of the controller, a high-high switch trips the pump and holds it tripped until the level is back below the high switch.

Polishing runs for `polish_for_h` at every multiple of `polish_every_h`, with power, with `polish_enable` set and with no leak.

## Points

In `points.yaml`. A point whose name contains `sub_` exists once per generator, for example `sub_a_level_pct` and `alarm_sub_a_low_level`. Writable: `transfer_enable` and `polish_enable`, both tier `T2`. Everything else is a status at tier `T0`.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `bulk_tank_m3` (two tanks) | 25 | m³ | assumed (SDD 3) |
| `sub_base_tank_l` | 4000 | l | assumed |
| `low_switch_pct`, `high_switch_pct` | 50, 90 | % | assumed |
| `low_alarm_pct` | 25 | % | assumed |
| `high_high_switch_pct` | 98 | % | assumed |
| `transfer_l_per_h` | 1500 | l/h | assumed |
| `transfer_pump_kw` | 1.5 | kW | assumed |
| `polishing_kw` | 2.2 | kW | assumed |
| `polish_every_h`, `polish_for_h` | 168, 4 | h | assumed |

## Faults

In `faults.py`: transfer pump failure, level switch stuck wet or dry, interstitial leak. A switch stuck dry is how an overfill happens: the controller keeps filling until the high-high switch trips the pump. Scenario inputs set a tank level at the start of a scenario.

## Validation cases

- The module contract suite.
- At rest nothing moves. A tank drains at the generator's burn rate, refills from the low switch to the high switch, and the fuel in the system changes only by what was burned.
- With its transfer pump failed, a tank reaches its low-level alarm and then runs empty; the other generators keep their fuel.
- Each fault does what the table above says. Pumps stop on a leak and without power.
- Scenario `OP-07`.

## Known limits

- Volumes, switch levels and pump rates are assumed; the reference specification gives the equipment, not its sizing.
- One transfer pump per sub-base tank, no standby pump, no day tank.
- Fuel quality is not modelled: polishing has a schedule and a power draw and no effect on the generators.
- A leak is a detector state. No fuel leaves the system through it.
