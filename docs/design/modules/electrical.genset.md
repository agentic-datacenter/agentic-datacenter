# Module spec: `electrical.genset`

Generator set. Fidelity `F1`. Zone `Z1-PWR-{instance}`. Instances: one per train: `A`, `B`, `C`.

## Purpose

One standby generator with its controller: start, ramp, ready-to-load handshake, loading, cooldown, and the response of frequency and voltage to load steps.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `output` | provides | `electrical` |
| `ready_to_load` | provides | `signal` |
| `fault` | provides | `signal` |
| `start_request` | requires | `signal` |
| `fuel` | requires | `fuel` |

## Equations

- **Load step.** A change of load by a fraction *s* of the rating moves frequency by `-0.07 * s / 0.6` on an increase and `+0.10 * s / 0.6` on a decrease, and voltage by `-0.15 * s / 0.6` and `+0.20 * s / 0.6`. These are the class G3 limits (SDD 6.6), taken to be reached at a step of 60 % of the rating (assumed). A larger step gives a proportionally larger excursion, outside the class.
- **Recovery.** Each deviation decays exponentially with a time constant of one third of the recovery time (3 s for frequency, 4 s for voltage), which brings it to 5 % of its peak by the recovery time.
- **Fuel.** Burn is linear in load between the 25 % and 100 % rates, extended below 25 % and floored at half the 25 % rate.
- **Overload.** Load above 110 % of the rating for 10 s faults the set (assumed).

## State machine

`STOPPED` → `CRANKING` (3 s) → `RAMPING` → `READY_TO_LOAD`, 10 s after the request in total. `LOADED` while delivering power; `COOLDOWN` while running unloaded after having been loaded. The set runs for as long as the start request stands and stops when it is withdrawn; the cooldown time itself is held by the transfer controller. `FAULT` on a failed start, loss of fuel, sustained overload or a trip, until a manual reset.

## Points

State, ready and fault signals, load, frequency, voltage, fuel burn and a start counter at tier `T0`. `test_start_request` is tier `T2`: the one point an operator may write (SDD 8.2).

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `rated_kw` | 1800.0 | kW | `assumed: true` |
| `start_s` | 10.0 | s | `assumed: true` |
| `crank_s` | 3.0 | s | `assumed: true` |
| `fuel_l_per_h_full` | 430.0 | l/h | `assumed: true` |
| `fuel_l_per_h_quarter` | 130.0 | l/h | `assumed: true` |
| `overload_fraction` | 1.1 | - | `assumed: true` |
| `overload_s` | 10.0 | s | `assumed: true` |

## Faults

`start_failure` (the next start ends in a fault), `trip`, `reset`.

## Validation cases

- `packages/agentic-datacenter-plant/tests/electrical/test_sources_and_loads.py`: start time, stop, failed start and reset, loss of fuel, fuel burn at three loads, a load step at the class limit (dip and recovery of frequency and voltage), a step beyond the class, load rejection, sustained overload.
- The module contract suite.

The load-step response has closed-form answers at `F1`. It has not been compared with a measured or independently simulated set, which `F2` requires.

## Known limits

- Frequency and voltage follow a first-order recovery; there is no engine inertia, droop or regulator model behind it.
- The step at which the class limit is reached (60 % of rating) is an assumption; the standard ties it to the engine.
- The load bank and the monthly test profile are not modelled; `test_start_request` starts the set and nothing more.
- The set stops at once when the request is withdrawn.
