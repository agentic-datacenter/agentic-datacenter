# cooling.pod

The air side of one POD: server air handlers with chilled water coils, supply temperature and static pressure loops, dampers, the zone sensor arrays and leak detection.

- Fidelity: `F0` (stub only)
- Zone: `Z1-POD-{instance}`
- Instances: one per POD: `01` to `16`
- Spec: [`docs/design/modules/cooling.pod.md`](../../../../../../../docs/design/modules/cooling.pod.md)

## Stub behaviour

All IT heat is moved to the chilled water while water is available, at a fixed 8 K water temperature rise; none when it is not. The IT inlet is held at 22 °C in both cases. Fans draw no power and the fire signal is ignored.
