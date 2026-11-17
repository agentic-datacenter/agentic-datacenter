# electrical.genset

One standby generator with its controller: start, ramp, ready-to-load handshake, loading and cooldown.

- Fidelity: `F1`
- Zone: `Z1-PWR-{instance}`
- Instances: one per train: `A`, `B`, `C`
- Spec: [`docs/design/modules/electrical.genset.md`](../../../../../../../docs/design/modules/electrical.genset.md)

## Stub behaviour

The generator never starts: output dead, not ready to load, no fault, no fuel burned.
