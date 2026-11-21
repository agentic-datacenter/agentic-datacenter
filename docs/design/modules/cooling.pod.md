# Module spec: `cooling.pod`

POD cooling. Fidelity `F1`. Zone `Z1-POD-{instance}`. Instances: one per POD: `01` to `16`.

## Purpose

The air side of one POD: air handlers with chilled water coils, the supply air loop, and the thermal response of the hall. This module decides the primary harm metric of the cooling scenarios: whether a POD becomes thermally critical.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `chw` | requires | `hydronic` |
| `it_heat` | requires | `air_heat` |
| `fan_power` | requires | `electrical` |
| `fan_power_b` | requires | `electrical` |
| `fire_stop` | requires | `signal` |

## Equations

Supply-side air `Ts` (the IT inlet), return-side air `Tr` and the thermal mass `Tm` of the hall on the supply side, with airflow `m` through the IT equipment:

```text
Cs dTs/dt = m cp (T_in - Ts) + h (Tm - Ts)
Cm dTm/dt = h (Ts - Tm)
Cr dTr/dt = m cp (Ts - Tr) + Q_it + Q_fan
```

With the air handlers running, `T_in = Tr - Q_coil / (m cp)` and `Q_coil = valve * effectiveness * m cp * (Tr - T_chw)`. With them stopped, the IT equipment recirculates its own exhaust and `T_in = Tr`. The three equations sum to `Q_it + Q_fan - Q_coil`, so energy is conserved exactly.

With cooling lost, the supply side warms at about `Q / (Cs + Cm)`, the lumped form of SDD 6.2. The chilled water valve follows a PI loop on supply air temperature, limited by its stroke time. Water flow is the coil heat at a fixed 8 K water rise.

## State machine

**Air handlers.** Four units, three of which carry the design airflow at full speed (N+1), run together at one speed. A static pressure loop sets that speed: pressure is taken to follow the square of the share of the IT airflow the units deliver, and speed ramps toward its target over the drive ramp time. When the units deliver less air than the IT equipment draws, the shortfall recirculates from the exhaust side to the inlets; when they deliver more, the surplus bypasses the equipment. Energy is conserved in both cases.

**Restart.** After a mains failure the units stay off for a delay set by the POD's position, so PODs return in groups five seconds apart (`ADC-CTL-004`).

**Reboot.** While the controller reboots, the valve and the fan speed stay where they were and the process goes on (`ADC-CTL-005`).

**Zone mean.** Six zone sensors are read through the measurement service (ADR 0008). The supply air temperature the loop controls, and the one the critical flag judges, is the mean of the sensors in use. A sensor leaves the mean when it reports bad quality (in the same control step, and it returns by itself), when it has disagreed with the median of the others by more than 2 K for 30 s (latched), or when it has not changed for 120 s while that median moved by more than 0.3 K (latched). Each exclusion raises an event. With no usable sensor the valve holds its position.

The POD is **thermally critical** when supply air has been above 32 °C for more than 60 s; time spent critical is counted in minutes. The air handlers stop when their feed is dead or the fire signal is active.

The supply-side temperature `Ts` is the inlet temperature given back to the IT load of the POD. When it stays high the servers shut down (`electrical.it_load`), the IT heat goes to zero and the POD cools, or stops warming, from there.

## Points

Temperatures of the three nodes, coil heat, valve position, fan power, the critical flag and counter, and a leak alarm at tier `T0`. `supply_air_sp_c` is tier `T3`, 18 to 27 °C.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `thermal_mass_kj_per_k` | 4500.0 | kJ/K | `assumed: true` |
| `air_node_kj_per_k` | 300.0 | kJ/K | `assumed: true` |
| `mass_conductance_kw_per_k` | 60.0 | kW/K | `assumed: true` |
| `coil_effectiveness` | 0.9 | - | `assumed: true` |
| `fan_kw` | 6.0 | kW | `assumed: true` |
| `valve_stroke_s` | 60.0 | s | `assumed: true` |
| `critical_c, critical_hold_s` | 32.0, 60.0 | °C, s | `assumed: true` |
| `design_it_kw, design_airflow_kg_s` | 150.0, 12.0 | kW, kg/s | `assumed: true` |

## Faults

`valve_stuck` and `clear`; `leak` and `leak_clear`; `sensor_reset`; `ahu_fail` and `ahu_restore` with `unit`; `reboot` with `kind`.

## Validation cases

- `packages/agentic-datacenter-plant/tests/cooling/test_cooling_modules.py`: steady state at setpoint; time to the critical threshold with chilled water lost, fans lost and both, each inside 3 to 6 minutes (`ADC-PRC-004`); recovery; a setpoint step without large overshoot; warm water the coil cannot work with; the fire signal; exact energy conservation through a loss of cooling.
- `tests/scenario/test_thermal_runaway.py`: all sixteen PODs on the whole plant.
- The module contract suite.

## Known limits

- `thermal_mass_kj_per_k` is calibrated to the 3 to 6 minute target and to nothing else. SDD 14 lists it among the assumptions that most affect results.
- One supply-side node: no hot spots. The six zone sensors read that one temperature with a small fixed spread.
- Static pressure is a function of delivered airflow, not a duct model. Dampers and damper proof-of-open before fan start are not modelled.
- Leak isolation is manual and not modelled.
- The air handlers take two supplies and run on either, with no transfer time. The design document does not say how they are fed; a single feed made the loss of one generator a thermal runaway in a third of the PODs (found by scenario `OP-07`), so two feeds are assumed.
- The model advances once a second. Values that cross a port are reported at a resolution of 0.0001 (ADR 0006), and the module rests when it has reached steady state.
