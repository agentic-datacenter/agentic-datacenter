# Module spec: `sensors`

Sensor models. Fidelity `F1`. Zone `n/a`. Instances: one, for example `SENSORS`.

## Purpose

The model a measured point passes through before a controller or the supervisory layer sees it: accuracy, resolution and failure modes (SDD 6.5). It is the plant's measurement service (ADR 0008): other modules reach it through the kernel context, not through a port and not by import.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| none | | |

## Equations

A healthy sensor reads `true + offset`, rounded to the resolution. The offset is drawn once per sensor, uniformly within half the width of its accuracy class, from a random stream named by the sensor's tag. In the failure modes:

- `stuck`: the last reading, for ever.
- `drift`: `true + offset + rate * minutes since the fault`.
- `bias`: `true + offset + bias`.
- `noisy`: `true + offset + N(0, sigma)`.
- `bad`: the last reading, flagged bad quality.

## State machine

Per sensor: healthy, or one of the five modes above until cleared.

## Points

None of its own. Readings appear as points of the module that owns the sensor.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| `temperature_accuracy_c` | 0.5 | °C | `assumed: true` (the restricted reference gives the same class) |
| `humidity_accuracy_pct` | 5.0 | % RH | `assumed: true` |
| `resolution_digits` | 2 | decimals | `assumed: true` |

## Faults

`stuck`, `drift` with `rate_per_min`, `bias` with `offset`, `noisy` with `sigma`, `bad`, `clear`; each takes `tag`, written `module_id[instance].point`.

## Validation cases

- `packages/agentic-datacenter-plant/tests/sensors/test_zone_mean.py`: readings inside the accuracy class and at the resolution; reproducible from the seed; a bad sensor out of the zone mean within one control step and back when good (`ADC-CTL-006`); scenario OP-04, with a stuck sensor and a drifting sensor in one POD; a noisy sensor that stays in; a loop that holds its output with no usable sensor.
- The module contract suite.

## Known limits

- **Only the POD zone sensors pass through this module.** Every other measured point in the plant still reports its true value. SDD 6.5 says every measured point.
- No update period: a sensor is read whenever its owner steps.
- The offset is fixed for the life of a run; there is no slow ageing.
- Humidity sensors have an accuracy class and nothing reads them yet.
