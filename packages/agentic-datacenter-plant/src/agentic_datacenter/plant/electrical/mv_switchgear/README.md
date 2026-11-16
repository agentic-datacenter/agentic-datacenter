# electrical.mv_switchgear

The metal-clad 36 kV switchboard: two incomers, one feeder per unit substation, and the six protection relays that later speak IEC 61850.

- Fidelity: `F0` (stub only)
- Zone: `Z1-MV`
- Instances: one, for example `SWG-MV`; keys `trains`
- Spec: [`docs/design/modules/electrical.mv_switchgear.md`](../../../../../../../docs/design/modules/electrical.mv_switchgear.md)

## Stub behaviour

Every feeder follows incomer 1 while it is energized, otherwise incomer 2, otherwise it is dead. The whole feeder demand is drawn from the incomer in use. No breaker, no relay.
