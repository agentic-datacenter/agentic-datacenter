# cooling.pump_station

The packaged pump station: three variable-speed pumps, one controller panel each, two duty and one standby.

- Fidelity: `F0` (stub only)
- Zone: `Z1-CHW`
- Instances: one, for example `PHPS`
- Spec: [`docs/design/modules/cooling.pump_station.md`](../../../../../../../docs/design/modules/cooling.pump_station.md)

## Stub behaviour

A pipe: whatever flow the consumers ask for is delivered, with no pump power and no pump heat.
