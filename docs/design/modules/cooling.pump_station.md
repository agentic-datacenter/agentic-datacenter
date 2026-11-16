# Module spec: `cooling.pump_station`

Chilled water pump station. Fidelity `F1`. Zone `Z1-CHW`. Instances: one, for example `PHPS`.

## Purpose

The packaged pump station: three variable-speed pumps, each fed from a different train, two on duty and one standby.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `chw` | provides | `hydronic` |
| `chws_in` | requires | `hydronic` |
| `power_1` | requires | `electrical` |
| `power_2` | requires | `electrical` |
| `power_3` | requires | `electrical` |

## Equations

Speed is the highest of the speed the flow asks for (`flow / capacity`), the speed the differential pressure setpoint asks for (`sqrt(setpoint / rated)`, since head follows the square of speed) and a minimum. Power per pump is `rated * speed ** 3`. Pump power is added to the water as heat. When the running pumps cannot deliver the flow asked for, the supply temperature passed on rises by the undelivered share of the design water rise. Supply temperature follows its target with a 30 s lag.

## State machine

**Restart and reboot.** After a power interruption pump *n* waits *n* times five seconds (`ADC-CTL-004`). While the controller reboots the selection of duty pumps stands, so a pump that fails then is not replaced until the controller is back (`ADC-CTL-005`).

The first two usable pumps in the rotation run, starting from the lead pump; a pump is usable when its feed is energized and it has no fault. The standby takes over at the next one-second step.

## Points

Running flags, speed, power, flow and supply temperature at tier `T0`; `dp_sp_kpa` at tier `T3` and `lead_pump` at tier `T2`.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `pump_flow_kg_s` | 45.0 | kg/s | `assumed: true` |
| `pump_kw` | 30.0 | kW | `assumed: true` |
| `rated_dp_kpa` | 200.0 | kPa | `assumed: true` |
| `min_speed` | 0.3 | - | `assumed: true` |
| `transport_lag_s` | 30.0 | s | `assumed: true` |

## Faults

`pump_fail` and `pump_restore` with `pump`.

## Validation cases

- `packages/agentic-datacenter-plant/tests/cooling/test_cooling_modules.py`: duty and standby with takeover on a fault; power against the cube of speed; the differential pressure floor; no pump means no water; one pump at design flow delivers warmer water.
- The module contract suite.

## Known limits

- No pump curve and no system curve: flow is what the consumers ask for, up to capacity. A flow shortfall is expressed as a warmer supply, not as starved coils.
- The differential pressure loop is a speed floor, not a control loop with dynamics.
- Heat reported by consumers in the second in which the last pump stops is not passed upstream.
- The model advances once a second. Values that cross a port are reported at a resolution of 0.0001 (ADR 0006), and the module rests when it has reached steady state.
