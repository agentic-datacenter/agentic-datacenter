# Module spec: `electrical.ups`

Uninterruptible power supply. Fidelity `F1`. Zone `Z1-PWR-{instance}`. Instances: one per train: `A`, `B`, `C`.

## Purpose

One online UPS with its battery. It carries the IT load across a transfer, isolates it from the source while online, and releases its losses as heat to the electrical room.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `output` | provides | `electrical` |
| `heat` | provides | `air_heat` |
| `input` | requires | `electrical` |

## Equations

- **Battery.** `E(t + dt) = E(t) - P_out / efficiency * dt`. Capacity is the energy that carries the rated load for the autonomy time, so autonomy at full load equals the profile value and doubles at half load.
- **Online.** Output is nominal whatever the input, inside the input range. Input power is `P_out / efficiency` plus recharge. Losses `P_out / efficiency - P_out` are released as heat.
- **Recharge.** Limited to a fraction of the rating (10 %), until the battery is full.
- **Input range.** The input is accepted when energized with voltage and frequency within plus or minus 10 % of nominal.

## State machine

`ONLINE` while the input is accepted. `ON_BATTERY` when it is not and energy remains. `DEPLETED` when the battery is empty: the output drops. `BYPASS` after an inverter fault: the load sees the source directly, with no ride-through.

## Points

Mode, state of charge, output, input and loss power, remaining autonomy and an on-battery alarm; all tier `T0`. Nothing is writable from the network (SDD 8.2).

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `rated_kw` | 1200.0 | kW | `assumed: true` |
| `autonomy_s` | 300.0 | s | `assumed: true` |
| `efficiency` | 0.96 | - | `assumed: true` |
| `recharge_fraction` | 0.1 | - | `assumed: true` |
| `input_low_pu, input_high_pu` | 0.9, 1.1 | pu | `assumed: true` |
| `airflow_kg_s` | 4.0 | kg/s | `assumed: true` |

## Faults

`fault` (inverter out, load to bypass), `reset`, `set_soc` with `pct` for a partly discharged or degraded battery.

## Validation cases

- `packages/agentic-datacenter-plant/tests/electrical/test_sources_and_loads.py`: autonomy at full load for two profile values and at half load (`ADC-PRC-003`), a short outage with recharge at the limit, the input range, bypass, and power balance at every step through an outage and recharge (`ADC-PRC-001`).
- The module contract suite.

## Known limits

- Efficiency is constant. SDD 6.6 asks for efficiency as a function of load, capacity fade and rate dependence; none is modelled, so autonomy is exactly inversely proportional to load.
- Recharge has no losses.
- Overload is not limited: the UPS delivers whatever is asked.
- Transfer to battery and to bypass is instantaneous.
