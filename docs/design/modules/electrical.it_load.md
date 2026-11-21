# Module spec: `electrical.it_load`

IT load of one POD. Fidelity `F1`. Zone `Z1-POD-{instance}`. Instances: one per POD: `01` to `16`.

## Purpose

The IT equipment of one POD: power drawn from two feeds and the heat it releases. Fidelity `F1` on the electrical side only, with server fans and a thermal shutdown that respond to inlet temperature.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `heat` | provides | `air_heat` |
| `feed_a` | requires | `electrical` |
| `feed_b` | requires | `electrical` |
| `epo` | requires | `signal` |

## Equations

**Fans.** Server fan speed is `1 + 0.06 * max(0, T_inlet - 25)`, capped at 2.5, and fan power follows the cube of speed. At the reference inlet the fans take 3 % of the design load, so the design load is the total at 25 °C and below. Airflow follows speed. A warmer supply air setpoint therefore costs IT power, about four times the fan power at 35 °C (`ADC-FID-003`).

**Workload.** One of three traces: `steady`; `diurnal`, between 50 % and 100 % over a day; `accelerated`, which jumps to a new level between 40 % and 100 % every 30 to 300 s, from a seeded stream.

A feed is usable when energized and within plus or minus 10 % of nominal voltage. The workload is shared evenly by the usable feeds, and carried by one when the other is not usable. With no usable feed the load is dropped and the energy it would have drawn is counted. All power served is released as heat at a fixed airflow. Emergency power off removes the load without counting it as lost.

**Thermal shutdown.** Servers protect themselves from hot inlet air. The inlet temperature is the supply-side air of the POD (`cooling.pod`). When it has been above 40 °C for 60 s, the load of the POD trips: nothing is drawn from either feed, no heat is released, and the energy the workload asks for is counted as lost, like a dropped load. The ASHRAE A1 class allows inlet air up to 32 °C; a server's own protective shutdown is usually set some way above that, and 40 °C is a round value in that range. The load starts again when the inlet has been at or below 32 °C for 300 s. While the inlet is between the two, a tripped load stays off. Each trip and each restart raises the event `it_load.thermal_trip` with `active` and `inlet_c`.

## State machine

Two states, running and tripped. Running goes to tripped after `shutdown_hold_s` with the inlet above `shutdown_inlet_c`. Tripped goes to running after `restart_hold_s` with the inlet at or below `restart_inlet_c`. The timer starts again whenever the condition is broken. The protection runs on the one-second step.

## Points

Power served, power asked for, energy lost, a dropped flag, a thermal trip flag and the inlet temperature; all tier `T0`. The thermal trip flag is an urgent alarm.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `design_kw` | 150.0 | kW | `assumed: true` |
| `airflow_kg_s` | 12.0 | kg/s | `assumed: true` |
| `input_low_pu, input_high_pu` | 0.9, 1.1 | pu | `assumed: true` |
| `shutdown_inlet_c, shutdown_hold_s` | 40.0, 60.0 | °C, s | `assumed: true` |
| `restart_inlet_c, restart_hold_s` | 32.0, 300.0 | °C, s | `assumed: true` |

## Faults

Scenario input `set_load` with `fraction` of the design load.

## Validation cases

- `packages/agentic-datacenter-plant/tests/electrical/test_sources_and_loads.py`: sharing and takeover between feeds, energy lost while dropped, the input range, emergency power off, a thermal trip and its restart, a hot inlet shorter than the hold time, the protection timer through a snapshot.
- The module contract suite.

## Known limits

- The fan curve and the three traces are assumed shapes, not fitted to equipment or to recorded workloads.
- Power-supply hold-up is not modelled: a feed that is dead for one step is dead. The load returns as soon as a feed does.
- The thermal shutdown acts on the whole POD at once, on one inlet temperature. Real servers trip one by one, each on its own sensor, and a hot spot trips some before others.
- The shutdown temperature, the hold times and the automatic restart are assumed. Many sites restart servers after a thermal shutdown by hand; the restart hold stands for that delay.
- A tripped load still reports the airflow its fans would give, as a dropped load does. The air handlers of the POD follow that airflow, so they keep running and the POD can cool down.
