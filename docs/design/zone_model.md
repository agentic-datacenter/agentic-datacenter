# Zone and conduit model

Stage 0 deliverable. This is the working form of SDD-ADC-001, section 4: the zones as instances, the conduits as an allow matrix, and where each rule will be enforced and tested. The SDD stays normative; where this file and the SDD disagree, the SDD wins and this file is corrected.

The diagram is in [img/zone-conduit-model.svg](img/zone-conduit-model.svg).

## 1. What the model is for

- It is the input `agentic-datacenter-net` builds its virtual network and, in `compose` mode, its Docker networks from (Stage 6).
- It is the oracle for `conformance/test_zone_matrix`: every ordered pair of zone instances is either listed here as allowed or must fail to connect (`ADC-NET-001`).
- It is the documented zone model that the IEC 62443-3-2 workflow asks for. No formal risk assessment stands behind the target levels (SDD 14); they are engineering assumptions.

## 2. Zone instances

The SDD lists 12 zone types. Two of them are instantiated per unit, which gives 29 zone instances in the generic facility.

| Zone type | Instances | Count | Level | SL-T | Writable from the network |
| --- | --- | --- | --- | --- | --- |
| `Z0-PROT` | one | 1 | 0 to 1 | n/a, hardwired | Never |
| `Z1-MV` | one | 1 | 1 | 3 | Never (status-only relays, SDD 8.5) |
| `Z1-PWR-{A,B,C}` | one per power train | 3 | 1 | 3 | Generator test start only |
| `Z1-CHW` | one | 1 | 1 | 3 | Chiller enable and setpoints, pump station setpoint and duty |
| `Z1-POD-{01..16}` | one per POD | 16 | 1 | 2 | Supply air and static pressure setpoints |
| `Z1-FUEL` | one | 1 | 1 | 2 | Polishing schedule, transfer enable |
| `Z1-BLDG` | one | 1 | 1 | 1 | Not specified in the SDD (open point 6) |
| `Z2-SUP` | one | 1 | 2 | 3 | Origin of all legitimate writes |
| `Z2-SEC` | one | 1 | 2 | 2 | Nothing accepted from other zones |
| `Z3-DMZ` | one | 1 | 3.5 | 2 | Hosts the REMORA gate |
| `ZA-AGENT` | one | 1 | n/a | untrusted | n/a |
| `Z4-ENT` | one | 1 | 4 | 1 | n/a |

"Level 1 zones" below means the 23 instances of `Z1-*`.

The scalar SL-T is the maximum of the per-requirement vector, which the profile holds (SDD 4.1).

## 3. Allow matrix

Deny is the default. A flow is allowed only if a row here allows it, in the direction given. "Initiator" is the side that opens the connection; data may flow back on an established session unless the row says one-way.

| Conduit | Initiator | Responder | Instances | Carries | Direction of authority |
| --- | --- | --- | --- | --- | --- |
| `C1` | `Z2-SUP` | each level 1 zone | 23 | Modbus/TCP, BACnet/IP, SNMPv3, IEC 61850 MMS | Reads from supervisory hosts on the allowlist; writes only from the Supervisory Command Service address |
| `C2` | `Z2-SUP` | `Z3-DMZ` | 1 | OPC UA with signing and encryption, historian replication | Outward only; nothing in the DMZ can open it |
| `C3` | `Z4-ENT` | `Z3-DMZ` | 1 | HTTPS | Read-only API, no command verbs |
| `C4` | `ZA-AGENT` | REMORA gate in `Z3-DMZ` | 1 | HTTPS or MCP over mutual TLS | Reads and proposals; identity from the client certificate |
| `C5` | REMORA gate in `Z3-DMZ` | Supervisory Command Service in `Z2-SUP` | 1 | HTTPS over mutual TLS | Writes, each carrying a valid, unexpired, single-use decision reference |
| `C6` | `Z0-PROT` | each level 1 zone and `Z2-SUP` | 24 | Hardwired contacts, modelled as one-way signals | Status only; there is no reverse path in code |
| `C7` | `Z4-ENT` | jump host in `Z3-DMZ`, then `Z2-SUP` | 1 | Brokered remote session | Time-boxed, tied to a work permit, recorded |
| `C8` | `Z2-SEC` | `Z2-SUP` | 1 | Event feed | One-way events; no door command is accepted |

For `C3` the SDD writes the conduit as "`Z3-DMZ` to `Z4-ENT`"; the initiator is taken here to be the enterprise client calling the read-only API. See open point 3.

### Pairs that must fail

These follow from the default, and are named because each one is a property the demonstration depends on.

| Pair | Why it matters | Scenario or test |
| --- | --- | --- |
| `ZA-AGENT` to anything except the gate | The agent has no route to a controller; this is enforced by the network model, not by agent behaviour | `AD-02`, `AD-10`, `conformance/test_zone_matrix` |
| `Z1-PWR-A`, `-B`, `-C` to each other | A compromise must not cross the redundancy boundary | `conformance/test_zone_matrix` |
| Any `Z1-POD-nn` to any other | Blast radius stays at one POD | Same |
| Any level 1 zone to `Z2-SUP` as initiator | Controllers answer; they do not call out | Same |
| Anything to `Z0-PROT` | Protection and life safety have no network write path | `conformance/test_t0_unmapped`, `C6` reverse-path test |
| `Z2-SUP` to `Z2-SEC` | Supervisory cannot command doors | `C8` rule test |
| `Z4-ENT` to `Z2-SUP` directly | Remote access is brokered | `conformance/test_zone_matrix` |
| `Z3-DMZ` to any level 1 zone | Nothing in the DMZ talks to a controller | Same; see open point 1 |

## 4. Rules inside a conduit

`C1` is where most of the detail lives (`ADC-NET-002`). An allowlist entry is a tuple of client address, device, protocol, operation and address range, generated from the point database so it cannot drift from the point maps.

| Target zone | Read | Write |
| --- | --- | --- |
| `Z1-MV` | MMS read and report | Nothing. Control, setting-group, configuration-write and file services are dropped at the conduit and also refused by the relay (`ADC-IEC-003`) |
| `Z1-PWR-*` | Meters, breaker status, transfer controller, generator, UPS | Generator test start request only; transfer controller and UPS expose nothing writable |
| `Z1-CHW` | Chillers, pump panels, storage instrumentation | Chiller enable and supply setpoint; differential pressure setpoint and duty assignment |
| `Z1-POD-*` | POD controller, leak detection | Supply air and static pressure setpoints |
| `Z1-FUEL` | Levels, pump and leak status | Polishing schedule, transfer enable |
| `Z1-BLDG` | Not specified in the SDD | Not specified in the SDD |

Three properties hold for every conduit:

- A blocked attempt raises a security event with source zone, destination and rule within 5 simulated seconds (`ADC-NET-003`).
- Nothing in `Z0-PROT` and no tier `T0` command or setting has a protocol map, so no conduit rule can expose one; a tier `T0` status in a controller zone is mapped read-only (`ADC-NET-004`, ADR 0010).
- Modbus/TCP and BACnet/IP carry no authentication. The boundary rule is the compensating countermeasure, and the simulator says so in its outputs (SDD 4.4).

## 5. Enforcement points

| Run mode | Zone separation | Conduit rules |
| --- | --- | --- |
| `inproc` | Virtual network in `agentic_datacenter.net.virtual_net`: a connection between two endpoints succeeds only if a conduit joins their zones | `agentic_datacenter.net.conduits`, in the same process, deterministic |
| `compose` | One Docker network per zone | A conduit container on real sockets, driven by the same generated allowlists |

Both modes read one zone model, so the matrix test runs unchanged in each (`ADC-NET-001`).

## 6. Open points for the SDD

Found while turning section 4 into a matrix. Each needs an SDD change or a written decision before Stage 6; none is decided here.

1. **Data collector path.** SDD 8.3 has the data collector in `Z3-DMZ` polling critical points over Modbus/TCP at 1 s, and the requirement is real-time Modbus collection from the POD controllers. No conduit in 4.2 lets `Z3-DMZ` open a Modbus session to `Z2-SUP` or to a level 1 zone, and `C2` is initiated from `Z2-SUP` only. Either the collector reads a Modbus view served in `Z2-SUP` over a new, read-only conduit, or the supervisory side pushes over `C2`, or the collector moves into `Z2-SUP`.
2. **`C5` is the one inbound flow into `Z2-SUP` from the DMZ**, alongside the brokered `C7`. The SDD is clear that it exists; the allow matrix should state the single destination (the Supervisory Command Service address and port) so the conduit cannot be read as general DMZ-to-supervisory access.
3. **Initiator of `C3`.** Written as "`Z3-DMZ` to `Z4-ENT`" in 4.2. An HTTPS read API is normally called by the enterprise client. The matrix above assumes that; the SDD should say which side opens the connection.
4. **Time relay.** The DMZ holds a time relay and supervisory servers follow a simulated NTP source (SDD 7.5), but no conduit lists NTP. It can ride on `C2` if the supervisory side initiates.
5. **Alarm notification** leaves `Z2-SUP` toward people. If it is modelled at all it needs a conduit; if not, the SDD should say it is out of scope.
6. **Devices without a stated zone.** The SDD device table (8.2) lists six electrical room units with a writable return air setpoint, and section 3 lists outdoor air units and fan coils, but no row of 4.1 places the electrical room units, and 8.2 has no device row for `Z1-BLDG`. The electrical room units cool the UPS rooms of each train; whether they sit in `Z1-PWR-*`, `Z1-CHW` or `Z1-BLDG` changes the blast radius of a compromise and must be stated.
