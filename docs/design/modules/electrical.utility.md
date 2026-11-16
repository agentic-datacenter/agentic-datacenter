# Module spec: `electrical.utility`

Utility incomer. Fidelity `F1`. Zone `Z1-MV`. Instances: one per incomer, for example `INC-1`, `INC-2`.

## Purpose

One 36 kV utility incomer: the voltage and frequency the site is offered. The scenario drives it.

## Ports

| Port | Direction | Type |
| --- | --- | --- |
| `supply` | provides | `electrical` |

## Equations

The supply is energized whenever the voltage is above zero and carries the per-unit voltage and frequency last set. The power recorded is the demand placed on the incomer while it is energized.

## State machine

None. The incomer holds two numbers.

## Points

`voltage_pu`, `frequency_pu`, `load_kw`; all tier `T0` measurements.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| none | | | |

## Faults

Scenario inputs (see `faults.py`): `set` with `voltage_pu` and `frequency_pu` for a sag, swell or frequency excursion; `loss`; `restore`.

## Validation cases

- `packages/agentic-datacenter-plant/tests/electrical/test_sources_and_loads.py`: nominal, disturbed, lost and restored.
- The module contract suite.

## Known limits

- Single-phase loss is not modelled; the model has one voltage, not three.
- A disturbance is a step. Sags shorter than one 100 ms step are not represented.
- The incomer has no source impedance: its voltage does not depend on load.
