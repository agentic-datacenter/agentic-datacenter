# Module spec: `security`

Physical security signals. Fidelity `F1`. Zone `Z2-SEC`. Instances: one, for example `SEC`.

## Purpose

Doors, portals and perimeter zones emit events. The module is an event feed and a handful of status points. No door can be commanded through Agentic Datacenter.

## Ports

None.

## Equations

None. An event is counted and published on the event bus under `security.event` with its kind and place.

## State machine

Three latches: door forced, door held, intrusion. Each is set by an event of that kind and released by a `clear` of that kind.

## Points

In `points.yaml`: one counter per event kind and one alarm point per latch. Every point is tier `T0`; there is no command point.

## Parameters

| Parameter | Default | Unit | Source |
| --- | --- | --- | --- |
| none | | | |

## Faults

In `faults.py`: `event` with a kind (`granted`, `denied`, `forced`, `held`, `intrusion`) and a place, and `clear`.

## Validation cases

- The module contract suite.
- Each event is counted and published; forced, held and intrusion hold their alarm until cleared.
- No point is writable and no point is a command.

## Known limits

- Events are signals. Nothing models a person, a credential or an intruder acting on equipment.
- Places are free text; there is no door list.
