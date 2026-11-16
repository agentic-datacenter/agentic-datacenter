# ADR 0010: The network model in `inproc` mode, and which points have a protocol map

- **Status:** Accepted. Decision 3 was confirmed by the owner on 2026-11-12, and `ADC-NET-004` in the design document now says what it says.
- **Date:** 2026-11-12
- **SDD:** 4.1, 4.2, 7.1, 8.1, 8.2; requirements `ADC-NET-001` to `-004`

## Context

Stage 6 covers zones, conduits, protocol servers, IEC 61850 and `compose` mode. Three of those cannot be finished now: the IEC 61850 package waits for the licence decision (ADR 0004), `compose` mode puts protocol servers on real sockets, so it comes after them, and the protocol libraries of section 5 have to be chosen and pinned first. (An earlier version of this record said the build environment had no container runtime. That was wrong: Docker is installed and running there. The order of work is the reason, not the environment.) The zone and conduit model has none of these dependencies, and everything else in Stage 6 is driven by it.

Two statements in the design document collide once protocol maps are generated:

- `ADC-NET-004`: "No point with tier `T0` has a protocol map."
- Section 8.2: meters, breaker status, chiller status and leak detection are read over Modbus/TCP and BACnet/IP.

Section 7.1 defines the tiers for writable points and gives `T0` to the hardwired layer: interlocks, protective trips, emergency power off, fire cause and effect. It also says every point carries exactly one tier. The plant modules built in Stages 1 to 7 give `T0` to every status and measurement, on the reading that nobody may write them through any network path. Under that reading `ADC-NET-004` would leave nothing to read.

## Decision

1. **The zone and conduit model is data in `agentic_datacenter.net.zones`**, built from the module manifests plus the zones that exist in every facility. It is the oracle of the zone matrix test and will drive the conduit containers of `compose` mode unchanged.
2. **`inproc` mode enforces it in `agentic_datacenter.net.virtual_net`.** A request names source zone and host, destination zone and host, protocol, operation and address. A refusal is written to an append-only violation log and published on the event bus in the same step.
3. **Which points are mapped.** Nothing in `Z0-PROT` has a protocol map. No `T0` command or setting has one, in any zone. A `T0` status in a controller zone is mapped read-only. Only `T2` and `T3` commands and settings are mapped writable. This keeps what `ADC-NET-004` protects (threat A12: no network path writes a protection or life-safety point) and what 8.2 requires (status is readable).
4. **Protocol maps are generated, not written by hand**, in a fixed order from the point database: Modbus tables and register numbers, BACnet object types and instances, SNMP identifiers under a fictitious enterprise arc, and one OPC UA node per mapped point. The `C1` allowlist is generated from the same maps.
5. **The first protocol of a device class is its control protocol; a second one is a read-only view** (the Modbus server of a POD controller for real-time collection, the Modbus view of a UPS).

## Consequences

- `ADC-NET-001` to `-004` are tested in `inproc` mode only. `ADC-NET-001` asks for both run modes, so Stage 6 stays open and `[tool.agentic-datacenter] stage` is not raised.
- `ADC-NET-004` was reworded in the design document on 2026-11-12 to match decision 3. This is also how real plants are built: a protection relay's trip contact or a fire panel's state is seen by the BMS as a read-only status, while the trip and the interlock themselves have no network path.
- The open points of `zone_model.md` section 6 are unchanged. The data collector still has no conduit; the matrix test asserts that `Z3-DMZ` cannot reach a controller zone.
- The protocol servers, the latency model of 8.4 and IEC 61850 are not part of this decision.
