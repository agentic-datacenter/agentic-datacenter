# Module spec: `electrical.power_train`

LV power train with automatic transfer. Fidelity `F1`. Zone `Z1-PWR-{instance}`. Instances: one per train: `A`, `B`, `C`.

## Purpose

One 400/230 V power train: unit substation, main switchboard with a utility breaker and a generator breaker, and the automatic transfer controller. It implements the open-transition, delayed-transition sequence of SDD 7.2 and every failure response in that section, and it holds invariant `INV-ATO-1`.

The module has three parts that do not share code paths: `model.py` (breakers and bus), `controller.py` (the sequence, which sees only the I/O board) and `interlocks.py` (the hardwired interlock, which every close command passes through whoever issued it).

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `lv_bus` | provides | `electrical` |
| `gen_start_request` | provides | `signal` |
| `utility_feed` | requires | `electrical` |
| `gen_output` | requires | `electrical` |
| `gen_ready_to_load` | requires | `signal` |
| `gen_fault` | requires | `signal` |

## Equations

- **Bus.** The bus takes the voltage and frequency of the source whose breaker is closed, if that source is energized; otherwise it is dead.
- **Demand.** All demand on the bus is drawn from the source that carries it. A dead bus draws nothing.
- **Source acceptance.** A source that is accepted stays accepted while voltage and frequency are both inside the drop-out limits; a source that is not accepted becomes accepted when both are inside the pick-up limits. A tripped utility breaker makes the utility unacceptable whatever its voltage.
- **Breaker.** An operation completes one operating time (50 ms, assumed) after it is commanded. With a 100 ms step its effect is seen at the next step. A trip opens the breaker at once and holds it open until a manual reset.
- **Interlock.** A source breaker may close only when the other is open by its own contacts and has no close operation under way. The check is made when the command is given and again when the operation completes.

## State machine

**Reboot.** While the transfer controller reboots it does not scan: breakers and the start request stay where they were. The interlock is hardwired and still stands (`ADC-CTL-005`).

| State | Leaves when | To |
| --- | --- | --- |
| `ON_UTILITY` | utility not accepted, and no latched breaker failure | `START_DELAY` |
| `START_DELAY` | utility accepted again / `TDES` expired | `ON_UTILITY` / `WAIT_GENERATOR` (start requested) |
| `WAIT_GENERATOR` | utility accepted / generator ready | `ON_UTILITY` with cooldown / `PRE_TRANSFER` |
| `PRE_TRANSFER` | `TDNE` expired | `OPENING_UTILITY` |
| `OPENING_UTILITY` | breaker open / no feedback in time | `NEUTRAL_TO_GENERATOR` / `ON_UTILITY`, alarm, generator stopped |
| `NEUTRAL_TO_GENERATOR` | `TDPT` expired and generator ready | `CLOSING_GENERATOR` |
| `CLOSING_GENERATOR` | breaker closed / no feedback in time | `ON_GENERATOR` / `CLOSING_UTILITY`, alarm, generator stopped |
| `ON_GENERATOR` | utility accepted / generator fault / generator breaker tripped | `RETURN_DELAY` / `GENERATOR_FAULT` / `NEUTRAL_TO_UTILITY` (no `TDEN`) |
| `RETURN_DELAY` | utility leaves tolerance / `TDEN` expired | `ON_GENERATOR` / `OPENING_GENERATOR` |
| `OPENING_GENERATOR` | breaker open / no feedback in time | `NEUTRAL_TO_UTILITY` / `ON_GENERATOR`, alarm |
| `NEUTRAL_TO_UTILITY` | `TDPT` expired and utility accepted | `CLOSING_UTILITY` |
| `CLOSING_UTILITY` | breaker closed / no feedback in time | `ON_UTILITY`, `TDEC` cooldown starts / `NEUTRAL_TO_GENERATOR`, alarm |
| `GENERATOR_FAULT` | utility accepted / fault cleared and generator ready | `NEUTRAL_TO_UTILITY` / `NEUTRAL_TO_GENERATOR` |
| `LOCKED_OUT` | manual reset | by breaker position |

A protective trip (ground fault or instantaneous) of either source breaker goes to `LOCKED_OUT` from any state and opens both breakers. With the mode switch out of `AUTO` the sequence is suspended, the start request is dropped, and an alarm stands for as long as that lasts. A latched breaker-failure alarm blocks the transfer it concerns until reset.

The start request is held during every state that needs the generator and for `TDEC` after a retransfer.

## Points

Declared in `points.yaml` (37 points). Measurements, feedback, commands and alarms are tier `T0`. The five timers, the feedback time, the four acceptance limits and the mode switch are tier `T1`: adjustable at the device, never over the network (SDD 8.2).

## Parameters

Any setting point can be overridden by a profile parameter of the same name.

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `tdes_s` | 5.0 | s | `assumed: true` |
| `tdne_s` | 1.0 | s | `assumed: true` |
| `tdpt_s` | 1.0 | s | `assumed: true` |
| `tden_s` | 30.0 | s | `assumed: true` |
| `tdec_s` | 300.0 | s | `assumed: true` |
| `feedback_s` | 1.0 | s | `assumed: true` |
| `dropout_low_pu`, `pickup_low_pu`, `pickup_high_pu`, `dropout_high_pu` | 0.90, 0.95, 1.05, 1.10 | pu | `assumed: true` |
| Breaker operating time | 50 | ms | `assumed: true` (SDD 6.1) |

These are round values for the generic profile. The restricted reference profile sets its own.

## Faults

Accepted by `inject` (see `faults.py`): `util_brk_fail_open`, `util_brk_fail_close`, `gen_brk_fail_open`, `gen_brk_fail_close` (cleared by `clear_faults`); `util_brk_trip` and `gen_brk_trip` with `kind` `protective` or `other` (cleared by `reset`); the local actions `reset`, `set_mode`, `manual_close` and `manual_open`.

## Validation cases

- `packages/agentic-datacenter-plant/tests/electrical/test_power_train.py`: the sequence with its timings, and one test per row of the failure table in SDD 7.2 (`ADC-CTL-001`).
- A property test drives the train with random sequences of utility states, generator states, faults, trips, mode changes and manual breaker commands, and requires that the two breakers are never both closed at any step (`ADC-CTL-002`).
- Demand is drawn from the carrying source and from neither on a dead bus (`ADC-PRC-001`).
- The module contract suite.

Timing was not compared with an independent reference in a validation suite; that comparison is what `F2` requires.

## Known limits

- The controller is always powered. The one-second recovery after loss of both sources, and the panel UPS, are not modelled.
- Source acceptance uses voltage and frequency only; phase-sequence monitoring is not modelled.
- The generator is accepted on its ready-to-load signal, not on its own voltage and frequency.
- A manual breaker command in `AUTO` is overwritten by the controller at its next scan; the interlock applies either way.
- Events shorter than a step are resolved to the step in which their effect is seen.
