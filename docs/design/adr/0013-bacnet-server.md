# ADR 0013: The BACnet/IP server is bacpypes3, one router in front of a virtual network of controllers

- **Status:** Accepted for the design; the server is in the same PR.
- **Date:** 2026-11-13
- **SDD:** 5, 8, 8.2, 8.4; requirement `ADC-PRO-001`

## Context

Section 5 names `bacpypes3` for BACnet/IP, and ADR 0012 says every protocol library gets its own check before it is used. That was done on 2026-11-13 against the released package and its repository:

- Version 0.0.110, released 2026-09-24. Eight releases since March 2025, three of them in September 2026; the repository had commits two days before the check and is not archived.
- Licence: the package metadata declares `MIT` as its licence expression and carries the classifier "BSD License". Both are permissive, so either reading is acceptable in `agentic-datacenter-net` (ADR 0004). Neither the wheel, the source archive nor the repository root contains a licence text, so the declared expression is all there is to go on. That is recorded in `THIRD_PARTY_NOTICES.md` and is a question for the owner if Agentic-Datacenter is ever redistributed with its dependencies.
- Python: declares 3.8 and later and lists 3.12 among its classifiers; the server below runs on 3.12.
- No required dependencies. Pure Python, one wheel for every platform.
- Maturity: the version number is below 0.1 and the classifier says "Pre-Alpha". The project is nonetheless the maintained successor of `bacpypes`, by the same author, and the check found no other permissively licensed BACnet server stack for Python that is maintained: `BAC0` (2026.7.25) is LGPL-3.0 and is a layer on top of this library, and `bacpypes` had its last release, 0.19.0, in January 2025. The risk is an interface that moves between releases, not a library that is abandoned.
- It ships no type information, so the type checker sees it as untyped.

A protocol server in Agentic-Datacenter is a view of the point database (section 8): it answers with the value and quality the database holds in that step and refuses what the device would refuse. `agentic_datacenter.net.maps` already gives every point of the chiller plant, the POD controllers and the electrical room units a BACnet object type and instance, per device (ADR 0010).

BACnet/IP has nothing like the unit identifier of Modbus: a device is found at an address. Twenty controllers on one host are therefore either twenty UDP ports, or one BACnet router with the controllers on a network behind it.

## Decision

1. **Use `bacpypes3`, below version 0.1, for the transport, the network layer and the encoding.** The requests are answered by Agentic-Datacenter's own handlers from the point database; the library's object classes are used only for the device object each controller must have.
2. **One BACnet router on one UDP port, and every mapped controller a device on a virtual network behind it.** The router is on network 1, the controllers on network 2, and a controller's address there is its device number from the maps, which is also its device instance. This is how field controllers behind a building router look to a supervisory system, it keeps the server on one port like the Modbus server, and the library does the routing. A device that does not exist does not answer.
3. **What a controller serves.** Who-Is, ReadProperty and WriteProperty, and nothing else: every other confirmed service is rejected as unrecognized. For each mapped point one object of the type and instance the map gives, with `object-identifier`, `object-name` (the tag), `object-type`, `description`, `present-value`, `status-flags`, `event-state`, `reliability` and `out-of-service`; `units` on analog objects, `polarity` on binary inputs, `number-of-states` and `state-text` on multi-state values. The device object lists them in `object-list`.
4. **Values.** An analog point and a counter are a REAL, as the map makes a counter an analog input. A binary point is active or inactive. An enumerated status is the position of its state, counted from one, with the state names in `state-text`. `units` is the BACnet unit for the unit strings the plant uses and `no-units` for anything else.
5. **Quality.** `good` is no flag. Any other quality sets the `fault` flag, with `reliability` `communication-failure` for `stale` and `unreliable-other` for `uncertain` and `bad`. `out-of-service` and the flag of that name stay false: on a field controller they say that an operator has taken the point out of service, which the point database has no notion of. `in-alarm` stays false because alarms are a supervisory function (section 7.5).
6. **Errors.** An object that is not in the map: class `object`, code `unknown-object`. A property the object does not have: `property`, `unknown-property`. A write to anything but the present value of an object the map marks writable: `property`, `write-access-denied`. A value of the wrong datatype: `property`, `invalid-data-type`. A value the point's declaration does not allow: `property`, `value-out-of-range`. An array index on a property that is not an array: `property`, `property-is-not-an-array`; outside the array: `property`, `invalid-array-index`.
7. **A write goes the way a Modbus write goes**: checked against the point's declaration, then `PointDatabase.write_through`. A refused write to a read-only or missing object is a `net.device_violation` event with the same fields as the Modbus one, plus the address of whoever sent it, which BACnet lets the device see (section 8.4). The write priority is ignored, as the standard prescribes for a present value that is not commandable.
8. **The conformance test uses the `bacpypes3` client against the server on loopback**, with the route to the controller network given to the client instead of discovered by broadcast. As with Modbus, this shows that the view and the errors are right, not that another implementation interoperates.
9. **The library is a dependency of `agentic-datacenter-net` only.**

A spike on 2026-11-13 confirmed 2, 3, 6 and 8 on loopback: reads and a refused write through the router, an unrecognized service rejected, Who-Is answered by every controller, silence from an address with no device.

## Consequences

- Nothing in `Z0-PROT` and no `T0` command or setting can be reached, because nothing is served that the maps do not contain.
- Not served: ReadPropertyMultiple, change-of-value subscriptions, segmentation of long answers beyond what the library does by itself, priority arrays, alarms and events, trend logs, schedules, time synchronization, BBMD and foreign-device registration. A client that insists on ReadPropertyMultiple has to fall back to ReadProperty, as the standard lets it.
- The device object's remaining properties come from the library. Its vendor identifier is 999, the value the library's own samples use; no vendor's proprietary objects or properties are implemented. The library's device object would answer `local-time` and `local-date` from the host clock, so those two are refused as unknown properties (`ADC-KRN-003`).
- A REAL has seven significant digits. A counter above 16,777,216 loses its last digits on this protocol; the same sample is exact over Modbus and OPC UA.
- The response latency of section 8.4 is not modelled, as for Modbus.
- The upper bound on the dependency is the next minor version. Raising it means running the conformance test against the new release first.
- `compose` mode may give each controller an address of its own instead of a place behind one router. The view does not change if it does; only the server's wiring does.
- The mypy configuration gets an entry that treats `bacpypes3` as untyped. Everything Agentic-Datacenter takes from it is converted to plain values at the boundary in `agentic_datacenter.net.bacnet`.
