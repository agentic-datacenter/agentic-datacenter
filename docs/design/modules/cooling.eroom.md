# Module spec: `cooling.eroom`

Electrical room cooling. Fidelity `F1`. Zone `Z1-PWR-{instance}`. Instances: one per electrical POD: `A`, `B`, `C`.

## Purpose

The chilled water air conditioners of one electrical room, which remove the losses of that train's UPS.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `chw` | requires | `hydronic` |
| `ups_heat` | requires | `air_heat` |
| `power` | requires | `electrical` |

## Equations

`C dT/dt = Q_ups + Q_fan - Q_coil` with `Q_coil = valve * UA * (T - T_chw)`. The valve follows a PI loop on room temperature. Water flow is the coil heat at a fixed 8 K water rise.

## State machine

Running while the feed is energized and the units are not switched off.

## Points

Room temperature, coil heat, valve position and fan power at tier `T0`; `return_air_sp_c` at tier `T3`.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `room_kj_per_k` | 2000.0 | kJ/K | `assumed: true` |
| `coil_kw_per_k` | 12.0 | kW/K | `assumed: true` |
| `fan_kw` | 4.0 | kW | `assumed: true` |
| `design_heat_kw` | 33.0 | kW | `assumed: true` |

## Faults

`units_off` and `clear`.

## Validation cases

- `packages/agentic-datacenter-plant/tests/cooling/test_cooling_modules.py`: holds its setpoint, warms without water.
- The module contract suite.

## Known limits

- The N+1 pair of units is one lumped unit; a single unit failing is not modelled.
- The room temperature is given back to the UPS but the UPS does not derate on it.
- The zone of this module is an assumption (`zone_model.md`, section 6, point 6).
- The model advances once a second. Values that cross a port are reported at a resolution of 0.0001 (ADR 0006), and the module rests when it has reached steady state.
