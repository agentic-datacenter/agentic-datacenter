# cooling.chw_plant

The three air-cooled chillers and their plant controller: staging, rotation, restart after a power interruption.

- Fidelity: `F0` (stub only)
- Zone: `Z1-CHW`
- Instances: one, for example `CHW`
- Spec: [`docs/design/modules/cooling.chw_plant.md`](../../../../../../../docs/design/modules/cooling.chw_plant.md)

## Stub behaviour

Chilled water is always available at the supply temperature, whatever the heat returned. Electrical input is the returned heat divided by a fixed coefficient of performance, shared evenly over the power feeds that are energized.
