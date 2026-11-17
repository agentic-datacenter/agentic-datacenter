# electrical.it_load

The IT equipment of one POD: power drawn from two feeds, the heat it releases, and server fans that respond to inlet temperature.

- Fidelity: `F1`
- Zone: `Z1-POD-{instance}`
- Instances: one per POD: `01` to `16`
- Spec: [`docs/design/modules/electrical.it_load.md`](../../../../../../../docs/design/modules/electrical.it_load.md)

## Stub behaviour

Draws the design load, split evenly over the feeds that are energized, and all of it from one feed when the other is dead. Draws nothing when both are dead or emergency power off is active. All power drawn is released as heat at a fixed airflow.
