# Module spec: `electrical.mv_switchgear`

36 kV switchboard. Fidelity `F1`. Zone `Z1-MV`. Instances: one, for example `SWG-MV`; keys `trains`.

## Purpose

The metal-clad 36 kV switchboard: two incomers onto one bus, one feeder per unit substation, and a relay on each of them. It supplies the three power trains and it clears faults, locally and at tier `T0`. The relays are the ones that later serve IEC 61850 MMS (SDD 8.5); the number and placement of relays is an assumption of the design document.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `feeder` per `trains` | provides | `electrical` |
| `incomer_1` | requires | `electrical` |
| `incomer_2` | requires | `electrical` |

## Equations

- **Bus.** The bus is energized when at least one incomer breaker is closed onto an energized supply, and takes the voltage and frequency of the first such incomer. Demand is shared equally by the incomers in service.
- **Current.** Phase current is real power divided by `sqrt(3) * 36 kV * 0.95` (nominal voltage and an assumed power factor). A scenario can add a fault current at any node; it is seen by that node's relay and, shared, by the incomers in service.
- **Inverse time (PTOC).** IEC standard inverse: `t = TMS * 0.14 / ((I / Is) ** 0.02 - 1)`. The element integrates: each step adds `dt / t(I)` of its travel, and it resets at once when the current falls to pickup or below. When the travel completes inside a step the exact instant is kept, so the operating time does not depend on the 100 ms step.
- **Instantaneous (PIOC).** Operates in the step in which the current reaches its pickup, with an operating time of 20 ms (assumed).
- **Breaker.** The contacts part one breaker operating time (50 ms, assumed) after the relay operates. With a 100 ms step the feeder is seen dead at the first step boundary after that instant.
- **Bus elements.** Undervoltage, overvoltage, underfrequency and overfrequency report after a definite time (2 s, assumed) outside 0.9 to 1.1 per unit. The bus relay has no breaker and trips nothing.

## State machine

Per breaker: closed; tripped by `PTOC` or `PIOC` and held open until a manual reset at the relay; or opened locally. A tripped breaker cannot be closed before it is reset.

## Points

Expanded from templates in `points.yaml` for `inc_1`, `inc_2` and `fdr_<train>`: breaker position, tripping element, current, real power and operating time of the last trip (tier `T0`), and pickup current, time multiplier and instantaneous pickup (tier `T1`). The bus has voltage, frequency, four element flags and their definite time. No point is writable over the network.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `nominal_kv` | 36.0 | kV | `assumed: true` |
| `power_factor` | 0.95 | - | `assumed: true` |
| Feeder pickup, time multiplier, instantaneous pickup | 60, 0.1, 600 | A, -, A | `assumed: true` |
| Incomer pickup, time multiplier, instantaneous pickup | 180, 0.2, 2000 | A, -, A | `assumed: true` |
| `breaker_ms`, `instantaneous_ms` | 50, 20 | ms | `assumed: true` |
| `bus_low_pu`, `bus_high_pu`, element delay | 0.9, 1.1, 2 | pu, pu, s | `assumed: true` |

## Faults

`fault_current` with `node` and `amps`; `clear_fault`; `reset`, `manual_open` and `manual_close` with `breaker`. A node is `incomer_1`, `incomer_2` or `feeder[<train>]`.

`remote_request` with `relay`, `service` (`control`, `setting-group`, `write` or `file`) and `client` stands for a request that reached a relay over the network. The relay refuses it, publishes `protection.refused` and changes nothing (SDD 8.5). The same refusal on a real MMS socket is the IEC 61850 package's (`ADC-IEC-003`).

## Validation cases

- `packages/agentic-datacenter-plant/tests/electrical/test_mv_protection_curves.py`: operating time against the characteristic within 5 % at 1.5, 2, 3, 5, 10 and 20 times pickup; instantaneous operation within one control step and the breaker open one operating time later; no operation below pickup; reset when a fault clears before operation; a feeder relay clearing its fault before the incomer relays operate (`ADC-IEC-004`).
- `tests/scenario/test_op01.py`: opening feeder A drives the whole transfer and retransfer of train A.
- The module contract suite.

The curve is compared with its closed form, which is what `F1` asks for. Comparison with the IEC characteristic through an independent tool is `F2`.

## Known limits

- One current per breaker, not three phases; no earth-fault element, although the transfer controller's lockout row speaks of ground faults.
- A fault current is a number set by the scenario. There is no network model that would derive it from source impedance, and it does not depress the bus voltage.
- The two incomers run in parallel onto one bus. There is no bus section breaker and no incomer transfer scheme.
- No breaker-failure protection: if a feeder breaker did not open, only the slower incomer elements would clear the fault. Feeder breakers have no stuck-breaker fault to exercise that.
- The relays do not yet serve any protocol; that is Stage 6.
