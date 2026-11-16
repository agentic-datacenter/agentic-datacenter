"""The six protection relays as IEC 61850 devices (SDD 8.5).

This module is data and needs no protocol library. It says which logical
nodes each relay has, which data objects they hold, and which point of the
point database stands behind each served value. The engineering files and
the MMS servers are both generated from it.

Only names of logical nodes, data objects and attributes are used here; no
text of the standard is reproduced.

What the plant model does not have is not invented:

- There is no separate start signal, so ``Str.general`` follows ``Op.general``.
- The incomer relays carry ``PTUV1`` and ``PTOV1`` because section 8.5 lists
  them, but the plant computes the voltage elements once, for the bus relay.
  On the incomers their behaviour is ``off``.
- Voltage and frequency are served per unit, as the point database holds them.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from agentic_datacenter.supervisory.points import PointDatabase

MODULE_ID = "electrical.mv_switchgear"
LOGICAL_DEVICE = "LD0"
#: Simulated time zero on the relays' clocks: 2026-01-01T00:00:00Z, in milliseconds.
EPOCH_MS = 1_767_225_600_000

#: Logical nodes of each kind of relay, in served order (SDD 8.5).
LOGICAL_NODES: dict[str, tuple[str, ...]] = {
    "incomer": ("LLN0", "LPHD1", "XCBR1", "CSWI1", "MMXU1", "PTOC1", "PIOC1", "PTUV1", "PTOV1",
                "PTRC1"),
    "bus": ("LLN0", "LPHD1", "MMXU1", "PTUV1", "PTOV1", "PTUF1", "PTOF1"),
    "feeder": ("LLN0", "LPHD1", "XCBR1", "CSWI1", "MMXU1", "PTOC1", "PIOC1", "PTRC1"),
}  # fmt: skip


@dataclass(frozen=True)
class Attr:
    """One data attribute of a data-object type, or one member of a structure.

    Attributes:
        name: Attribute name.
        btype: Basic type as SCL writes it; ``Struct`` and ``Enum`` take *type*.
        fc: Functional constraint; empty for a member of a structure.
        type: Id of the structure or enumeration type.
        trigger: ``dchg``, ``qchg`` or empty.
        value: Configured value, if the type fixes one.
    """

    name: str
    btype: str
    fc: str = ""
    type: str = ""
    trigger: str = ""
    value: str = ""


@dataclass(frozen=True)
class Sub:
    """A sub data object of a data-object type."""

    name: str
    type: str


_STATUS = (Attr("q", "Quality", "ST", trigger="qchg"), Attr("t", "Timestamp", "ST"))
_MEASURED = (Attr("q", "Quality", "MX", trigger="qchg"), Attr("t", "Timestamp", "MX"))
_UNITS = Attr("units", "Struct", "CF", "Unit")
_STATUS_ONLY = Attr("ctlModel", "Enum", "CF", "CtlModels", value="status-only")

#: Data-object types: id -> (common data class, members).
DO_TYPES: dict[str, tuple[str, tuple[Attr | Sub, ...]]] = {
    "ENC_Mod": ("ENC", (Attr("stVal", "Enum", "ST", "Beh", "dchg", "on"), *_STATUS, _STATUS_ONLY)),
    "ENS_Beh": ("ENS", (Attr("stVal", "Enum", "ST", "Beh", "dchg", "on"), *_STATUS)),
    "ENS_Health": ("ENS", (Attr("stVal", "Enum", "ST", "Health", "dchg", "Ok"), *_STATUS)),
    "LPL": ("LPL", (Attr("vendor", "VisString255", "DC", value="Agentic Datacenter"),
                    Attr("swRev", "VisString255", "DC", value="simulated"),
                    Attr("d", "VisString255", "DC"))),
    "DPL": ("DPL", (Attr("vendor", "VisString255", "DC", value="Agentic Datacenter"),
                    Attr("model", "VisString255", "DC", value="simulated protection relay"))),
    "SPS": ("SPS", (Attr("stVal", "BOOLEAN", "ST", trigger="dchg"), *_STATUS)),
    "INS": ("INS", (Attr("stVal", "INT32", "ST", trigger="dchg"), *_STATUS)),
    "SPC": ("SPC", (Attr("stVal", "BOOLEAN", "ST", trigger="dchg"), *_STATUS, _STATUS_ONLY)),
    "DPC": ("DPC", (Attr("stVal", "Dbpos", "ST", trigger="dchg"), *_STATUS, _STATUS_ONLY,
                    Attr("Oper", "Struct", "CO", "Operate"))),
    "MV": ("MV", (Attr("mag", "Struct", "MX", "AnalogueValue", "dchg"), *_MEASURED, _UNITS)),
    "CMV": ("CMV", (Attr("cVal", "Struct", "MX", "Vector", "dchg"), *_MEASURED, _UNITS)),
    "WYE": ("WYE", (Sub("phsA", "CMV"), Sub("phsB", "CMV"), Sub("phsC", "CMV"))),
    "ACT": ("ACT", (Attr("general", "BOOLEAN", "ST", trigger="dchg"), *_STATUS)),
    "ACD": ("ACD", (Attr("general", "BOOLEAN", "ST", trigger="dchg"),
                    Attr("dirGeneral", "Enum", "ST", "Direction", "dchg", "unknown"), *_STATUS)),
    "ASG": ("ASG", (Attr("setMag", "Struct", "SP", "AnalogueValue"), _UNITS)),
    "ING": ("ING", (Attr("setVal", "INT32", "SP"),)),
}  # fmt: skip

#: Structure types: id -> members.
DA_TYPES: dict[str, tuple[Attr, ...]] = {
    "AnalogueValue": (Attr("f", "FLOAT32"),),
    "Vector": (Attr("mag", "Struct", type="AnalogueValue"),),
    "Unit": (Attr("SIUnit", "Enum", type="SIUnit", value="none"),
             Attr("multiplier", "Enum", type="Multiplier")),
    "Originator": (Attr("orCat", "Enum", type="OrCat"), Attr("orIdent", "Octet64")),
    "Operate": (Attr("ctlVal", "BOOLEAN"), Attr("origin", "Struct", type="Originator"),
                Attr("ctlNum", "INT8U"), Attr("T", "Timestamp"), Attr("Test", "BOOLEAN"),
                Attr("Check", "Check")),
}  # fmt: skip

#: Enumerations: id -> ordinal -> literal. Only the literals the relays use.
ENUM_TYPES: dict[str, dict[int, str]] = {
    "Beh": {1: "on", 2: "blocked", 3: "test", 4: "test/blocked", 5: "off"},
    "Health": {1: "Ok", 2: "Warning", 3: "Alarm"},
    "CtlModels": {0: "status-only", 1: "direct-with-normal-security", 2: "sbo-with-normal-security",
                  3: "direct-with-enhanced-security", 4: "sbo-with-enhanced-security"},
    "Direction": {0: "unknown", 1: "forward", 2: "backward", 3: "both"},
    "OrCat": {0: "not-supported", 1: "bay-control", 2: "station-control", 3: "remote-control",
              4: "automatic-bay", 5: "automatic-station", 6: "automatic-remote", 7: "maintenance",
              8: "process"},
    "SIUnit": {1: "none", 5: "A", 29: "V", 33: "Hz", 62: "W"},
    "Multiplier": {0: "", 3: "k"},
}  # fmt: skip

_BEH = ("Beh", "ENS_Beh")
_ELEMENT = (_BEH, ("Str", "ACD"), ("Op", "ACT"))
#: Logical-node types: id -> (class, data objects).
LN_TYPES: dict[str, tuple[str, tuple[tuple[str, str], ...]]] = {
    "LLN0": ("LLN0", (("Mod", "ENC_Mod"), _BEH, ("Health", "ENS_Health"), ("NamPlt", "LPL"))),
    "LPHD": ("LPHD", (("PhyNam", "DPL"), ("PhyHealth", "ENS_Health"), ("Proxy", "SPS"))),
    "XCBR": ("XCBR", (_BEH, ("Loc", "SPS"), ("OpCnt", "INS"), ("Pos", "DPC"), ("BlkOpn", "SPC"),
                      ("BlkCls", "SPC"))),
    "CSWI": ("CSWI", (_BEH, ("Pos", "DPC"))),
    "MMXU_FEED": ("MMXU", (_BEH, ("TotW", "MV"), ("A", "WYE"))),
    "MMXU_BUS": ("MMXU", (_BEH, ("PhV", "WYE"), ("Hz", "MV"))),
    "PTOC": ("PTOC", (*_ELEMENT, ("StrVal", "ASG"), ("TmMult", "ASG"))),
    "PIOC": ("PIOC", (*_ELEMENT, ("StrVal", "ASG"))),
    "PTRC": ("PTRC", (_BEH, ("Tr", "ACT"), ("Op", "ACT"))),
    **{f"{c}_OFF": (c, _ELEMENT) for c in ("PTUV", "PTOV")},
    **{f"{c}_BUS": (c, (*_ELEMENT, ("OpDlTmms", "ING")))
       for c in ("PTUV", "PTOV", "PTUF", "PTOF")},
}  # fmt: skip


def ln_type(kind: str, node: str) -> str:
    """Return the logical-node type id of *node* on a relay of *kind*."""
    cls = node.rstrip("0123456789") if node != "LLN0" else node
    if cls == "MMXU":
        return "MMXU_BUS" if kind == "bus" else "MMXU_FEED"
    if cls in ("PTUV", "PTOV", "PTUF", "PTOF"):
        return f"{cls}_BUS" if kind == "bus" else f"{cls}_OFF"
    return cls


@dataclass(frozen=True)
class Binding:
    """One served attribute and the point behind it (SDD 8.5, "Point mapping").

    Attributes:
        ied: Relay tag, for example ``IED-FDR-A``.
        ref: Object reference inside the relay, for example ``LD0/MMXU1.TotW.mag.f``.
        fc: Functional constraint.
        tag: Tag of the point in the point database.
        convert: How the point value becomes the attribute value: ``float``,
            ``bool``, ``dbpos`` (closed is on), ``ms`` (seconds to milliseconds),
            ``equals:X`` or ``differs:X`` (an enumerated status against ``X``).
    """

    ied: str
    ref: str
    fc: str
    tag: str
    convert: str


@dataclass(frozen=True)
class Relay:
    """One protection relay.

    Attributes:
        tag: Its tag in the facility, for example ``IED-FDR-A``.
        name: Its IED name in SCL and on the wire, for example ``IED_FDR_A``.
        kind: ``incomer``, ``bus`` or ``feeder``.
        device: The module instance it belongs to.
        bindings: Every served attribute that follows a point.
        settings: Configured values by reference, such as units and descriptions.
    """

    tag: str
    name: str
    kind: str
    device: str
    bindings: tuple[Binding, ...]
    settings: Mapping[str, str]

    @property
    def logical_nodes(self) -> tuple[str, ...]:
        """The logical nodes of this relay, in served order."""
        return LOGICAL_NODES[self.kind]

    @property
    def domain(self) -> str:
        """The name of its logical device on the wire."""
        return f"{self.name}{LOGICAL_DEVICE}"

    def reference(self, ref: str) -> str:
        """Return *ref* (``LD0/...``) as a client addresses it on the wire."""
        return f"{self.name}{ref}"


def _units(node: str, data: str, unit: str, multiplier: str = "") -> dict[str, str]:
    base = f"{LOGICAL_DEVICE}/{node}.{data}.units"
    return {f"{base}.SIUnit": unit, f"{base}.multiplier": multiplier}


def _breaker_relay(tag: str, kind: str, device: str, b: str) -> Relay:
    def bind(ref: str, fc: str, point: str, convert: str) -> Binding:
        return Binding(tag, f"{LOGICAL_DEVICE}/{ref}", fc, f"{device}.{b}_{point}", convert)

    bindings = [
        bind("XCBR1.Pos.stVal", "ST", "brk_closed", "dbpos"),
        bind("CSWI1.Pos.stVal", "ST", "brk_closed", "dbpos"),
        bind("MMXU1.TotW.mag.f", "MX", "kw", "float"),
        *(bind(f"MMXU1.A.phs{p}.cVal.mag.f", "MX", "current_a", "float") for p in "ABC"),
        bind("PTOC1.Str.general", "ST", "trip", "equals:PTOC"),
        bind("PTOC1.Op.general", "ST", "trip", "equals:PTOC"),
        bind("PTOC1.StrVal.setMag.f", "SP", "pickup_a", "float"),
        bind("PTOC1.TmMult.setMag.f", "SP", "tms", "float"),
        bind("PIOC1.Str.general", "ST", "trip", "equals:PIOC"),
        bind("PIOC1.Op.general", "ST", "trip", "equals:PIOC"),
        bind("PIOC1.StrVal.setMag.f", "SP", "inst_a", "float"),
        bind("PTRC1.Tr.general", "ST", "trip", "differs:NONE"),
        bind("PTRC1.Op.general", "ST", "trip", "differs:NONE"),
    ]
    settings = {
        **_units("MMXU1", "TotW", "W", "k"),
        **{k: v for p in "ABC" for k, v in _units("MMXU1", f"A.phs{p}", "A").items()},
        **_units("PTOC1", "StrVal", "A"),
        **_units("PIOC1", "StrVal", "A"),
    }
    if kind == "incomer":
        for node in ("PTUV1", "PTOV1"):
            settings[f"{LOGICAL_DEVICE}/{node}.Beh.stVal"] = "off"
    return _relay(tag, kind, device, bindings, settings)


def _bus_relay(device: str) -> Relay:
    tag = "IED-BUS"

    def bind(ref: str, fc: str, point: str, convert: str) -> Binding:
        return Binding(tag, f"{LOGICAL_DEVICE}/{ref}", fc, f"{device}.bus_{point}", convert)

    bindings = [
        *(bind(f"MMXU1.PhV.phs{p}.cVal.mag.f", "MX", "v_pu", "float") for p in "ABC"),
        bind("MMXU1.Hz.mag.f", "MX", "f_pu", "float"),
    ]
    elements = (("PTUV1", "undervoltage"), ("PTOV1", "overvoltage"),
                ("PTUF1", "underfrequency"), ("PTOF1", "overfrequency"))  # fmt: skip
    for node, point in elements:
        bindings += [
            bind(f"{node}.Str.general", "ST", point, "bool"),
            bind(f"{node}.Op.general", "ST", point, "bool"),
            bind(f"{node}.OpDlTmms.setVal", "SP", "element_delay_s", "ms"),
        ]
    return _relay(tag, "bus", device, bindings, {})


def _relay(
    tag: str, kind: str, device: str, bindings: list[Binding], settings: dict[str, str]
) -> Relay:
    settings[f"{LOGICAL_DEVICE}/LLN0.NamPlt.d"] = f"{tag}: {kind} relay of {device}"
    return Relay(tag, tag.replace("-", "_"), kind, device, tuple(bindings), dict(settings))


def relays(points: PointDatabase) -> list[Relay]:
    """Return the relays of every 36 kV switchboard in the point database, sorted by tag.

    A breaker is recognised by its ``<breaker>_brk_closed`` point; ``inc_<n>``
    is an incomer and ``fdr_<train>`` a feeder, as the plant module names them.
    """
    out: list[Relay] = []
    devices = sorted({t.rpartition(".")[0] for t in points.tags() if t.startswith(MODULE_ID + "[")})
    for device in devices:
        names = [t.rpartition(".")[2] for t in points.tags() if t.startswith(device + ".")]
        out.append(_bus_relay(device))
        for name in names:
            if not name.endswith("_brk_closed"):
                continue
            breaker = name.removesuffix("_brk_closed")
            kind = "incomer" if breaker.startswith("inc_") else "feeder"
            tag = "IED-" + breaker.upper().replace("_", "-")
            out.append(_breaker_relay(tag, kind, device, breaker))
    return sorted(out, key=lambda r: r.tag)
