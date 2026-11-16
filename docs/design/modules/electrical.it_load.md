# Module spec: `electrical.it_load`

IT load of one POD. Fidelity `F1`. Zone `Z1-POD-{instance}`. Instances: one per POD: `01` to `16`.

## Purpose

The IT equipment of one POD: power drawn from two feeds and the heat it releases. Fidelity `F1` on the electrical side only.

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

## State machine

None.

## Points

Power served, power asked for, energy lost, a dropped flag and the inlet temperature; all tier `T0`.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `design_kw` | 150.0 | kW | `assumed: true` |
| `airflow_kg_s` | 12.0 | kg/s | `assumed: true` |
| `input_low_pu, input_high_pu` | 0.9, 1.1 | pu | `assumed: true` |

## Faults

Scenario input `set_load` with `fraction` of the design load.

## Validation cases

- `packages/agentic-datacenter-plant/tests/electrical/test_sources_and_loads.py`: sharing and takeover between feeds, energy lost while dropped, the input range, emergency power off.
- The module contract suite.

## Known limits

- The fan curve and the three traces are assumed shapes, not fitted to equipment or to recorded workloads.
- Power-supply hold-up is not modelled: a feed that is dead for one step is dead. The load returns as soon as a feed does.
