# electrical.utility

One 36 kV utility incomer: the voltage and frequency the site is offered, driven by the scenario.

- Fidelity: `F0` (stub only)
- Zone: `Z1-MV`
- Instances: one per incomer, for example `INC-1`, `INC-2`
- Spec: [`docs/design/modules/electrical.utility.md`](../../../../../../../docs/design/modules/electrical.utility.md)

## Stub behaviour

The supply is always energized at nominal voltage and frequency. Demand is accepted and ignored.
