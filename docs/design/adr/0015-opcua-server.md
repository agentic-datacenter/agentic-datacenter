# ADR 0015: The OPC UA server is asyncua, one read-only node per mapped point

- **Status:** Proposed. Decision 1 (an LGPL library under a BUSL-1.1 repository) is the owner's to confirm, as the licence position of ADR 0004 was. Nothing here is legal advice.
- **Date:** 2026-11-13
- **SDD:** 4.2 (`C2`), 5 ("verify the current major version and pin it in Stage 6"), 8.1, 8.3, 8.4; requirements `ADC-PRO-001`, `-002`

## Context

Section 5 names `asyncua` for OPC UA and asks that its current version be verified before it is used. That was done on 2026-11-13 against the released package:

- Version 2.1.0, released 2026-10-06. The 2.0 line started in June 2026 and the 1.x line had releases into March 2026, so the project is maintained. It still classifies itself as beta.
- It declares Python 3.10 to 3.13 and ships type information. The checks here ran on Python 3.12.
- Required dependencies: `aiosqlite` (MIT), `anyio` (MIT), `cryptography` (Apache-2.0 or BSD-3-Clause), `python-dateutil` (BSD-3-Clause), `pytz` (MIT), `sortedcontainers` (Apache-2.0), `typing-extensions` (PSF-2.0). Only `aiosqlite` and `pytz` are new to the lock.
- **Licence: LGPL-3.0-or-later.** This is the first copyleft library outside `agentic-datacenter-iec61850`.

**The licence, read against how Agentic Datacenter uses the library.** Agentic Datacenter imports `asyncua` as an unmodified package that `uv` installs from PyPI next to it. No file of the library is copied into this repository and none is changed. In the terms of the LGPL that makes `agentic-datacenter-net` a work that uses the library, and an installed Agentic Datacenter a combined work. The LGPL does not ask that such a work carries the LGPL itself. It asks, when the combined work is conveyed to someone else:

1. a prominent notice that the library is used and that it is under the LGPL, with the licence texts (GPL-3.0 and LGPL-3.0) supplied;
2. that the recipient can replace the library with a modified version of it and still run the combined work. A Python package resolved at import time from the recipient's own environment meets this without further measures, as long as Agentic Datacenter does not bundle the library into a frozen executable;
3. that the terms of the combined work do not stop the recipient from modifying the library part for their own use, or from reverse engineering to debug such modifications. BUSL-1.1 restricts production use of the licensed work; it places no restriction on a third-party library and does not forbid reverse engineering.

While the repository is private and nothing is conveyed, none of these is triggered. The conclusion is that the dependency is acceptable for a private BUSL-1.1 repository, with the obligations above recorded in `THIRD_PARTY_NOTICES.md` for the day Agentic Datacenter is distributed. The upper bound `<3` in `pyproject.toml` keeps a future major version, which could change licence, from arriving unnoticed.

**Where the server sits.** Section 8.3 lists OPC UA among the northbound interfaces: one server in `Z2-SUP` that exposes the point tree read-only. It is not a field device. Its only conduit is `C2`, from `Z2-SUP` to `Z3-DMZ`, which is read-only and which only the supervisory side may open (`agentic_datacenter.net.zones`, `zone_model.md` section 3). `agentic_datacenter.net.maps` already generates its map: one entry per mapped point, host `opcua-server` in `Z2-SUP`, never writable.

A spike on 2026-11-13 confirmed on loopback: 800 variables whose value attribute is computed on every read through the library's value callback; a status code and two timestamps of our choosing arriving unchanged at the client; `BadNodeIdUnknown` for a node that does not exist; `BadUserAccessDenied` for a write to a variable without write access; a `Basic256Sha256` sign-and-encrypt session between two self-signed application certificates.

The same spike found that **the library does not enforce the security policy by itself**. A server configured with the sign-and-encrypt policy alone still lets a client open an unsecured channel (needed for discovery), create and activate a session on it, and read. The reference client refuses to do so because no endpoint matches, but that check is in the client.

## Decision

1. **Use `asyncua` 2.1 as an unmodified, separately installed dependency of `agentic-datacenter-net` only**, bounded `>=2.1,<3`, on the licence reading above.
2. **The server is the host `opcua-server` in `Z2-SUP`, a view of the point database.** It serves exactly the points that `agentic_datacenter.net.maps` maps to OPC UA under the rules of ADR 0010: nothing in `Z0-PROT`, no `T0` command or setting, and nothing from a module that has no southbound protocol. Section 8.3 says "the full point tree"; it is read here as the full tree of mapped points, because ADR 0010 decision 3 is the later and more specific statement.
3. **Node ids.** Namespace `urn:agentic-datacenter:points` is namespace index 2. A point is the variable `ns=2;s=<tag>`, as in section 8.1. Its parent is one object per device, `ns=2;s=<module>[<instance>]`, directly under the standard `Objects` folder. The browse name of a variable is the point name; its description is the point's.
4. **What a read returns.** The value attribute is computed from the point database at the moment of the read, never stored in the address space.
   - Value: `Double` for analog points, `Boolean` for binary points, `UInt64` for counters, and the state name as a `String` for an enumerated status.
   - Status code from the point quality: `good` is `Good`, `uncertain` is `Uncertain`, `stale` is `UncertainLastUsableValue` (the value is the last one polled), `bad` is `Bad`.
   - Source timestamp: the simulated time the point was polled. Server timestamp: the simulated time of the read. Both are simulated milliseconds added to a fixed epoch, 2000-01-01T00:00:00Z, because the kernel has no calendar date. The wall clock is not used.
5. **Nothing is writable.** `C2` is read-only and section 8.3 makes the view read-only; southbound writes belong to the Supervisory Command Service. Every variable has read access only, the built-in remote administrator of the library is switched off, and a write to any attribute is answered `BadUserAccessDenied`. A refused write to a point is a device violation event (section 8.4). Because nothing can be written there is no out-of-range case; the range check stays where writes are accepted.
6. **Security.** Section 8.3 and `C2` ask for sign and encrypt.
   - Given an application certificate and key, the server offers one endpoint, `Basic256Sha256` with sign and encrypt, accepts anonymous identity only, and refuses to activate a session on a channel that carries no client certificate. That last rule is ours and closes the gap found in the spike.
   - Without a certificate it offers the unsecured endpoint and binds to loopback only; any other address is refused even with the external-bind override. This is the `inproc` case, where both ends are one process on one machine and the conduit is enforced by the virtual network, and it is what the conformance test reads.
   - Certificates are deployment material. None is generated by Agentic Datacenter and none is committed. Any client certificate is accepted; a trust list comes with `compose` mode.
7. **The conformance test uses the `asyncua` client against the server on loopback**, as ADR 0012 decided for Modbus and with the same limit: it shows the view is right, not that another implementation interoperates.
8. **`ADC-PRO-002` is tested from a table of protocols**, each with a reader that returns the value and, where the protocol carries one, the quality. Modbus carries no quality in a register read, so for Modbus the quality compared is absent and the value is the last polled one. BACnet and SNMP join the table when their servers exist.

## What is not served

- Subscriptions and monitored items. The library notifies on a stored write, and values here are computed on read, so a monitored item would not follow the plant. Clients poll.
- History, methods, events and alarms, and node management.
- The reverse connection that `C2` implies. The conduit is opened from `Z2-SUP`, and in OPC UA the client normally opens the connection. The library's server cannot call out to a client. In `inproc` mode the virtual network decides who may talk to whom; for `compose` mode this stays open and is taken with the conduit containers.
- Response latency (section 8.4), as for Modbus.
- Engineering units and ranges as OPC UA properties.

## Consequences

- The standard `Server` object in namespace 0 is the library's. Its start time and build date are wall-clock values set by the library, and its once-a-second current-time update is switched off. They never reach simulator state, and nothing in namespace 2 depends on them. Session timeouts and nonces inside the library also use the wall clock and the system random source; this is transport, not simulation.
- `THIRD_PARTY_NOTICES.md` carries the LGPL obligations. Before any distribution: ship the licence texts, do not freeze the library into an executable, and do not vendor or patch it in this repository. A change the library needs goes upstream.
- If the owner does not accept decision 1, the alternative is a different OPC UA stack; none under a permissive licence is known for Python, so the server would be dropped from Stage 6 by a design change.
- The source address of a refused write is not known to the view, as for Modbus; the conduit records it.
