# electrical.power_train

One 400/230 V power train: unit substation, main switchboard with utility and generator breakers, and the automatic transfer controller.

- Fidelity: `F1`
- Zone: `Z1-PWR-{instance}`
- Instances: one per train: `A`, `B`, `C`
- Spec: [`docs/design/modules/electrical.power_train.md`](../../../../../../../docs/design/modules/electrical.power_train.md)

## Stub behaviour

The switchboard bus follows the utility feed. The generator is never requested and never loaded, so loss of the feed is loss of the bus.
