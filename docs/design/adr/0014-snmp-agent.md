# ADR 0014: The SNMP agent is pysnmp 7, serving SNMPv3 read-only from its own instrumentation

- **Status:** Accepted for the design; the agent itself follows in the same PR, after its tests.
- **Date:** 2026-11-13
- **SDD:** 5 ("`pysnmp` or a maintained successor ... choose at Stage 6 and record in an ADR"), 4.2 (conduit `C1`), 8, 8.2, 8.4; requirement `ADC-PRO-001`

## Context

Section 5 leaves the SNMP library open because its maintenance has changed hands. The candidates were checked on 2026-11-13 against the metadata of the package index and, for the one chosen, against the installed package:

| Package | Latest release | Licence | State |
| --- | --- | --- | --- |
| `pysnmp` | 7.1.32, 2026-11-07 | BSD-2-Clause (licence file in the package; the metadata has no licence field) | The original project name, now released by LeXtudio. Three releases in the last two months. Python 3.11 to 3.15 declared. One required dependency, `pyasn1` (BSD-2-Clause). |
| `pysnmp-lextudio` | 6.3.0, 2024-10-06 | BSD-2-Clause | Its own summary says it is deprecated in favour of `pysnmp`. |
| `pysnmplib` | 6.0.0, 2026-09-29 | BSD-2-Clause | A separate fork. Requires `pycryptodomex` and a forked `pyasn1` under another distribution name. |
| `puresnmp` | 2.0.2, 2026-10-27 | MIT | Known as a client library without an agent; not installed or examined further. |
| `snmp-agent` | 0.2.3, 2022-02-23 | MIT | No release in four years; not examined further. |

What was looked at in `pysnmp` 7.1.32:

- It is asyncio-native: the transport is an asyncio datagram protocol and the client calls (`get_cmd`, `next_cmd`, `bulk_cmd`, `set_cmd`, `walk_cmd`) are coroutines.
- The agent side separates the protocol engine (message processing, the user-based security model, the GET, GETNEXT, GETBULK and SET responders) from the management instrumentation, which is an interface of three calls: read, read-next and write. A context name can be registered with any object that implements them.
- HMAC-SHA authentication uses the standard library only. Privacy (DES, AES) imports `cryptography`, which is not a dependency of the package and is not in section 5.
- It ships no type information.

A protocol server in Agentic Datacenter is a view of the point database (section 8): it answers with the value and quality the database holds in that step. Section 8.2 gives the UPS two protocols, SNMPv3 and Modbus/TCP, and says nothing on a UPS is writable from `Z2-SUP`. `agentic_datacenter.net.maps` already gives every mapped UPS point an identifier `1.3.6.1.4.1.99999.<device>.<index>.0` under a fictitious enterprise arc.

## Decision

1. **Use `pysnmp` 7.1 (`>=7.1.32,<8`) for the agent**, as a dependency of `agentic-datacenter-net` only. It is the maintained continuation under the name section 5 gives, it is permissively licensed, and it needs nothing but `pyasn1`.
2. **The library's protocol engine is used; its MIB tree is not.** The default context is registered with Agentic Datacenter's own instrumentation, which asks an `SnmpView`. The view is plain Python with no sockets and no library types: identifier in, type and integer out. The library's built-in objects (the system group, the SNMP statistics) are therefore not visible to a manager; the agent serves the fictitious enterprise subtree and nothing else.
3. **SNMPv3 only, with one user at level authNoPriv.** Sections 4.2 and 8.2 name SNMPv3 and no other version, so SNMPv1 and SNMPv2c messages are not answered; there is no community string. The user (`agentic-datacenter-monitor`, HMAC-SHA-256, key `agentic-datacenter-simulation-only`) is a constant in the source and is not a secret: the agent binds to loopback or a container network, and the simulator holds nothing to protect. A request without authentication, or with the wrong key, gets no data. Privacy is left out because it would add `cryptography`, a dependency outside section 5; it is revisited with `compose` mode, where the conduit is a real network.
4. **GET, GETNEXT and GETBULK are served.** A walk goes through the view's next-identifier function, which orders identifiers arc by arc as numbers. The exceptions are those of the protocol: `noSuchObject` for an identifier that is under no object of the view, `noSuchInstance` for an object of the view named without its instance `.0` or with another instance, `endOfMibView` after the last identifier.
5. **SET is refused with `notWritable` for every identifier**, mapped or not, and nothing is written. Each variable of a refused SET is published as a `net.device_violation` event, the same kind the Modbus view publishes for a refused write, and kept in the view's violation list. Unlike the Modbus library, this one tells the agent who is asking, so the event carries the source address section 8.4 asks for. Should `agentic_datacenter.net.maps` ever mark an SNMP map writable, the agent still refuses: the SNMP view is read-only by this decision, not by the absence of writable points today.
6. **Encoding.** SNMP has no floating-point type in common use, and UPS network cards publish scaled integers. Stated here so that a reader of the wire needs nothing else:

   | Point kind | SNMP type | Value |
   | --- | --- | --- |
   | `analog_in`, `analog_setting` | `Integer32` | the value times 1000, rounded to nearest, limited to the range of the type |
   | `counter` | `Counter64` | the count |
   | `binary_in`, `binary_cmd` | `Integer32` | 1 for true, 2 for false |
   | `enum_status` | `Integer32` | the position of the state in the point's declared list, counted from 1 |

   The Modbus view of the same device sends the state's position counted from 0 and the analog value as a float; each follows the custom of its protocol.
7. **Quality is a parallel subtree.** For a value at `1.3.6.1.4.1.99999.<device>.<index>.0` the quality of the same sample is at `1.3.6.1.4.1.99999.0.<device>.<index>.0`, an `Integer32`: 1 good, 2 uncertain, 3 bad, 4 stale. Arc 0 is free by construction, because `agentic_datacenter.net.maps` numbers devices from 1. A value whose quality is not good is still answered with the last value held, as a network card does when it has lost its UPS; the manager reads the quality to know.
8. **No notifications.** The design document asks for no trap or inform anywhere, so none is sent. Arc 0 under an enterprise is where SMIv1 traps were numbered; the quality subtree would move if notifications were added.
9. **Tier `T0` commands and everything in `Z0-PROT` are not reachable.** `agentic_datacenter.net.maps` generates no map for them (ADR 0010), and the view refuses to be built from a map that names one.
10. **The conformance test uses the `pysnmp` client against the agent on loopback, over UDP, on a port the operating system picks.** As in ADR 0012, server and client share a library: the test shows that the view is right and the errors are the ones asked for, not interoperability with another implementation.

A spike on 2026-11-13 confirmed 2 to 5 on loopback: a GET answered from a hand-written instrumentation, `noSuchInstance`, a walk ending in `endOfMibView`, GETBULK, a SET answered `notWritable` (error-status 17, error-index 1), no answer to an SNMPv2c request, a refusal of the wrong key and of an unauthenticated request, and the source address of the request available to the instrumentation.

## Consequences

- The library is untyped, so its imports carry an ignore for mypy and the calls into it are checked only by the tests.
- The library reads the wall clock and the system random source internally (engine time, message identifiers, the engine identifier). That is outside the kernel and does not touch simulated state; what the agent answers depends only on the point database.
- The agent answers at once; the response latency of section 8.4 is not modelled, as for Modbus.
- A manager that probes `sysObjectID` or `sysUpTime` before it polls gets `noSuchObject`. If a real monitoring tool is ever pointed at the simulator, a small system group is the first addition.
- Privacy, more than one user and access-control views are not there. They belong to `compose` mode and get their own record if `cryptography` is to be added.
- BACnet and OPC UA libraries get the same check and their own record before they are used.
