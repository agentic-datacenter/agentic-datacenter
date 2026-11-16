# cooling.eroom

The chilled water air conditioners of one electrical POD, N+1 units on return-air control.

- Fidelity: `F0` (stub only)
- Zone: `Z1-PWR-{instance}`
- Instances: one per electrical POD: `A`, `B`, `C`
- Spec: [`docs/design/modules/cooling.eroom.md`](../../../../../../../docs/design/modules/cooling.eroom.md)

## Stub behaviour

All UPS heat is moved to the chilled water while water is available, at a fixed 8 K water temperature rise. The room is held at 22 °C. The units draw no power.
