# ADR 0012: The Modbus/TCP server is pymodbus, driven by its action callback

- **Status:** Accepted.
- **Date:** 2026-11-12
- **SDD:** 5 ("verify the current major version and pin it in Stage 6"), 8.2, 8.4; requirements `ADC-PRO-001`, `-002`

## Context

Section 5 names `pymodbus` for Modbus/TCP and asks that its current version be verified before it is used. That was done on 2026-11-12 against the released package:

- Version 3.16.2, licence BSD-3-Clause, no required dependencies.
- The data-store classes that most examples use (`ModbusDeviceContext`, `ModbusSequentialDataBlock`, `ModbusServerContext`) log that they are deprecated and will be removed in version 4. Their replacement is `SimDevice` with `SimData` blocks.
- `SimDevice` takes an asynchronous `action` callback that is called for every request with the function code, the address, the count, the registers concerned and, for a write, the values. It may change the registers before a read is answered and may refuse a request with an exception code.

A protocol server in Agentic-Datacenter is a view of the point database (section 8): it must answer with the value and quality the database holds in that step, and it must refuse what the device would refuse.

## Decision

1. **Use `pymodbus` 3.16 for the server, through `SimDevice` and its `action` callback**, not through the deprecated data-store classes. The callback copies the mapped points into the registers on a read and applies or refuses a write.
2. **One Modbus device per mapped module instance**, with the unit id and the four tables of `agentic_datacenter.net.maps`. Analog values are IEEE 754 single precision in two registers, high word first; an enumerated status is its index in one register.
3. **A write is accepted only at a register the map marks writable**, and only with a value the point's declaration allows. Otherwise the answer is exception 2 (illegal address) or 3 (illegal value), and the attempt is a device violation event with the source address (section 8.4).
4. **The conformance test uses the `pymodbus` client against the server on loopback.** Server and client share a library, so the test shows that the view is right and the exceptions are the ones asked for; it does not show interoperability with another implementation. A second client is a later addition.
5. **The library is a dependency of `agentic-datacenter-net` only.**

A spike on 2026-11-12 confirmed 1 to 3 on loopback: a live value read as two registers, an accepted write, exception 3 for a value out of range and exception 2 for an address outside the map. An unknown unit id was answered with exception 4 by the library; whether that or silence is right for a device that does not exist is decided with the server.

## Consequences

- The server is written against an interface the library is still moving toward. A version 4 release is expected to keep it; the lock pins the version until that is checked.
- `compose` mode puts these servers on container networks; `inproc` mode binds them to loopback and only when a test or a demonstration asks for it (`ADC-SAF-001`).
- BACnet, SNMP and OPC UA libraries get the same check and their own record before they are used.
