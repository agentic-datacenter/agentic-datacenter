# Module spec: `cooling.tes`

Thermal energy storage. Fidelity `F1`. Zone `Z1-CHW`. Instances: one, for example `TES-1`.

## Purpose

The chilled water storage tank, in series between the chillers and the pumps. It exists because a chiller is unavailable for three minutes after any power interruption.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `chws_out` | provides | `hydronic` |
| `chws_in` | requires | `hydronic` |

## Equations

The store holds `mass * cp * usable_rise` of cooling. When water arrives from the plant warmer than the supply setpoint by `dT`, the tank cools it back with `flow * cp * dT` from the store, for as long as charge remains, and returns that much less heat to the plant. When the plant has held its setpoint for 60 s and the tank is not full, the tank recharges at a limited rate by asking the plant for that much more.

## State machine

Passing through, discharging, or recharging.

## Points

Charge, the two status flags, discharge power and outlet temperature at tier `T0`. `supply_sp_c` is tier `T3` and must be changed together with the plant's setpoint, which is why the chilled water contracts write both.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `volume_m3` | 45.0 | m³ | `assumed: true` |
| `usable_rise_k` | 8.0 | K | `assumed: true` |
| `recharge_kw` | 250.0 | kW | `assumed: true` |

## Faults

Scenario input `set_charge` with `pct`.

## Validation cases

- `packages/agentic-datacenter-plant/tests/cooling/test_cooling_modules.py`: a full tank is transparent; with the chillers off it carries the design load for about ten minutes; it holds supply temperature while discharging; it recharges at its limit.
- `tests/scenario/test_thermal_runaway.py`: with every chiller tripped the PODs do not notice for at least eight minutes.
- `tests/property/test_energy_balance.py` (`ADC-PRC-002`).

## Known limits

- A store of energy, not a stratified tank: no thermocline, no mixing, no standing loss. SDD 6.2 asks for two nodes.
- The tank has its own copy of the supply setpoint. A plant setpoint raised without it makes the tank discharge to hold the old one.
- Discharge is not limited by flow or by a valve.
- The model advances once a second. Values that cross a port are reported at a resolution of 0.0001 (ADR 0006), and the module rests when it has reached steady state.
