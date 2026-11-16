# Module spec: `cooling.chw_plant`

Chilled water plant. Fidelity `F1`. Zone `Z1-CHW`. Instances: one, for example `CHW`.

## Purpose

The three air-cooled chillers, each fed from a different train, and the plant controller that stages them.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `chws` | provides | `hydronic` |
| `ambient` | requires | `weather` |
| `power_1` | requires | `electrical` |
| `power_2` | requires | `electrical` |
| `power_3` | requires | `electrical` |

## Equations

The loop water has one temperature `T` and heat capacity `C`:

```text
C dT/dt = Q_returned - Q_chillers
Q_chillers = clip(Q_returned + C (T - setpoint) / tau, 0, capacity)
```

so the chillers hold the setpoint while they have the capacity, and the loop warms by exactly the heat they cannot remove. With every chiller off, water leaves at return temperature. Capacity per chiller is `rated * (1 - 0.012 (T_amb - 35))` and the coefficient of performance `cop * (1 - 0.02 (T_amb - 35))`, both clipped. Electrical input at part load is `(0.15 + 0.85 PLR)` of full-load input. The coefficient of performance also rises by 2.5 % per kelvin of supply temperature above the 18 °C design value (assumed), which is what a chilled water setpoint raise saves.

## State machine

**Restart and reboot.** After a power interruption chiller *n* is locked out for 180 s plus 20 s for each chiller before it, so the chillers do not return in the same second (`ADC-CTL-004`). While the plant controller reboots, nothing is staged and no replacement is started; each chiller carries on by itself (`ADC-CTL-005`).

Per chiller: `OFF`, `STARTING` (90 s), `RUNNING`, `TRIPPED` until reset, and `LOCKED_OUT` from a power interruption until 180 s after power returns. The plant wants a number of chillers, two at the start. It adds one when part-load ratio has been above 85 % for 5 minutes and drops one when it has been below 50 % for 15 minutes. It runs the first that many usable chillers in the rotation from the lead chiller, starts a replacement at once when one is lost, and stops a surplus chiller only when its replacement is running.

## Points

Chiller states, supply temperature, cooling, power, part-load ratio and capacity at tier `T0`. Chiller enables and the lead chiller are tier `T2`. The supply setpoint (16 to 21 °C) and the two staging thresholds are tier `T3`.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `chiller_kw` | 1600.0 | kW | `assumed: true` |
| `cop` | 4.5 | - | `assumed: true` |
| `design_ambient_c` | 35.0 | °C | `assumed: true` |
| `loop_kj_per_k` | 83720.0 | kJ/K | `assumed: true` |
| `start_s` | 90.0 | s | `assumed: true` |
| `restart_lockout_s` | 180.0 | s | `assumed: true` |
| `stage_up_after_s, stage_down_after_s` | 300.0, 900.0 | s | `assumed: true` |

## Faults

`chiller_trip` and `chiller_reset` with `chiller`.

## Validation cases

- `packages/agentic-datacenter-plant/tests/cooling/test_cooling_modules.py`: two chillers at the design load with one in standby and about 600 kW input; better efficiency in cooler weather; standby start on a trip; the 180 s lockout; staging up and down; every chiller off; a setpoint change; exact energy conservation.
- `tests/scenario/test_design_point.py` (`ADC-PRC-010`) and `tests/property/test_energy_balance.py` (`ADC-PRC-002`).

## Known limits

- **The generic chillers are 1,600 kW, not the 1,200 kW of the design document.** The heat load at the design point is about 2,650 kW (IT plus UPS losses, fans and pumps), which two 1,200 kW chillers cannot carry, and which would sit above the 85 % stage-up threshold for anything under about 1,560 kW. The design document's own numbers do not balance here; this is reported to its owner.
- Capacity and efficiency are linear in ambient temperature. SDD 6.6 asks for the DOE-2 curve set.
- No minimum run or off time, no low-flow or low-ambient trip, no weekly rotation by itself.
- Chillers share load equally and have no individual temperatures.
- The model advances once a second. Values that cross a port are reported at a resolution of 0.0001 (ADR 0006), and the module rests when it has reached steady state.
