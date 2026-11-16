# electrical.ups

One online UPS with its battery: carries the IT load across a transfer and reports its losses as heat to the electrical room.

- Fidelity: `F0` (stub only)
- Zone: `Z1-PWR-{instance}`
- Instances: one per train: `A`, `B`, `C`
- Spec: [`docs/design/modules/electrical.ups.md`](../../../../../../../docs/design/modules/electrical.ups.md)

## Stub behaviour

A wire: the output follows the input and the input draws exactly the output demand. No battery, no losses, no heat.
