"""Engineering files for the relays: one SCD for the site, one ICD per relay type (SDD 8.5).

The files are generated from :mod:`agentic_datacenter_iec61850.model` and nothing else, and
the output is the same bytes for the same input: no dates, no generated
identifiers, fixed order. :func:`parse` reads a generated file back into the
plain description the MMS server is built from, so the model a client is
configured against and the model the server exposes are the same file.

The reader understands the files this module writes. It is not a general SCL
reader.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from agentic_datacenter_iec61850.model import (
    DA_TYPES,
    DO_TYPES,
    ENUM_TYPES,
    LN_TYPES,
    LOGICAL_DEVICE,
    LOGICAL_NODES,
    Attr,
    Relay,
    Sub,
    ln_type,
)

NAMESPACE = "http://www.iec.ch/61850/2003/SCL"
ACCESS_POINT = "AP1"
SUBNETWORK = "Z1-MV"
#: Data sets of a relay with a breaker, and of the bus relay: name -> members.
_EVENTS = {
    "breaker": ("XCBR1.Pos", "PTRC1.Tr", "PTOC1.Op", "PIOC1.Op"),
    "bus": ("PTUV1.Op", "PTOV1.Op", "PTUF1.Op", "PTOF1.Op"),
}
_MEASUREMENTS = {
    "breaker": ("MMXU1.TotW", "MMXU1.A"),
    "bus": ("MMXU1.PhV", "MMXU1.Hz"),
}
#: Report control blocks of every relay: name, buffered, data set.
REPORTS = (
    ("brcbEvents", True, "dsEvents"),
    ("urcbEvents", False, "dsEvents"),
    ("urcbMeas", False, "dsMeas"),
)


class SclError(ValueError):
    """A file is not one this module wrote."""


@dataclass(frozen=True)
class Leaf:
    """One basic attribute of a relay's data model.

    Attributes:
        ref: Reference inside the relay, for example ``LD0/MMXU1.A.phsA.cVal.mag.f``.
        fc: Functional constraint.
        btype: Basic type as SCL writes it.
        depth: How many names after the logical node are data objects (1, or 2
            under a sub data object); the rest are attributes.
        trigger: ``dchg``, ``qchg`` or empty.
        value: Configured value, or empty. For an enumeration, the literal.
        ordinal: For an enumeration with a configured value, its ordinal.
    """

    ref: str
    fc: str
    btype: str
    depth: int
    trigger: str = ""
    value: str = ""
    ordinal: int | None = None


@dataclass(frozen=True)
class DataSet:
    """One data set: its name in ``LLN0`` and its members as ``LD0/LN.DO[FC]``."""

    name: str
    members: tuple[str, ...]


@dataclass(frozen=True)
class Report:
    """One report control block as served: ``brcbEvents01`` and so on."""

    name: str
    buffered: bool
    data_set: str
    report_id: str


@dataclass(frozen=True)
class Ied:
    """One relay as an engineering file describes it."""

    name: str
    tag: str
    kind: str
    logical_nodes: tuple[str, ...]
    leaves: tuple[Leaf, ...]
    data_sets: tuple[DataSet, ...]
    reports: tuple[Report, ...]
    setting_groups: tuple[int, int]

    @property
    def domain(self) -> str:
        """The name of the logical device on the wire."""
        return f"{self.name}{LOGICAL_DEVICE}"


# -- writing ---------------------------------------------------------------------------------


def _templates(root: ET.Element, kinds: Sequence[str]) -> None:
    templates = ET.SubElement(root, "DataTypeTemplates")
    used_ln = sorted({ln_type(kind, node) for kind in kinds for node in LOGICAL_NODES[kind]})
    used_do: set[str] = set()
    for type_id in used_ln:
        cls, objects = LN_TYPES[type_id]
        node = ET.SubElement(templates, "LNodeType", id=type_id, lnClass=cls)
        for name, do_type in objects:
            ET.SubElement(node, "DO", name=name, type=do_type)
            used_do.add(do_type)
    for type_id in list(used_do):
        used_do |= {m.type for m in DO_TYPES[type_id][1] if isinstance(m, Sub)}
    used_da: set[str] = set()
    used_enum: set[str] = set()

    def note(attr: Attr) -> None:
        if attr.btype == "Enum":
            used_enum.add(attr.type)
        elif attr.btype == "Struct" and attr.type not in used_da:
            used_da.add(attr.type)
            for member in DA_TYPES[attr.type]:
                note(member)

    def attribute(parent: ET.Element, element: str, attr: Attr) -> None:
        fields = {"name": attr.name, "bType": attr.btype}
        if attr.type:
            fields["type"] = attr.type
        if attr.fc:
            fields["fc"] = attr.fc
        if attr.trigger:
            fields[attr.trigger] = "true"
        item = ET.SubElement(parent, element, fields)
        if attr.value:
            ET.SubElement(item, "Val").text = attr.value
        note(attr)

    for type_id in sorted(used_do):
        cdc, members = DO_TYPES[type_id]
        node = ET.SubElement(templates, "DOType", id=type_id, cdc=cdc)
        for member in members:
            if isinstance(member, Sub):
                ET.SubElement(node, "SDO", name=member.name, type=member.type)
            else:
                attribute(node, "DA", member)
    for type_id in sorted(used_da):
        node = ET.SubElement(templates, "DAType", id=type_id)
        for attr in DA_TYPES[type_id]:
            attribute(node, "BDA", attr)
    for type_id in sorted(used_enum):
        node = ET.SubElement(templates, "EnumType", id=type_id)
        for ordinal, literal in sorted(ENUM_TYPES[type_id].items()):
            ET.SubElement(node, "EnumVal", ord=str(ordinal)).text = literal


def _instance_values(node: ET.Element, name: str, settings: dict[str, str]) -> None:
    """Write the configured values under logical node *name* as DOI, SDI and DAI."""
    prefix = f"{LOGICAL_DEVICE}/{name}."
    for ref in sorted(r for r in settings if r.startswith(prefix)):
        path = ref.removeprefix(prefix).split(".")
        parent = node
        for depth, part in enumerate(path):
            element = "DOI" if depth == 0 else ("DAI" if depth == len(path) - 1 else "SDI")
            found = next(
                (c for c in parent if c.tag in ("DOI", "SDI", "DAI") and c.get("name") == part),
                None,
            )
            parent = found if found is not None else ET.SubElement(parent, element, name=part)
        ET.SubElement(parent, "Val").text = settings[ref]


def _ied(root: ET.Element, name: str, tag: str, kind: str, settings: dict[str, str]) -> None:
    ied = ET.SubElement(
        root,
        "IED",
        name=name,
        desc=tag,
        type=kind,
        manufacturer="Agentic-Datacenter",
        configVersion="1",
    )
    services = ET.SubElement(ied, "Services")
    for service in ("DynAssociation", "GetDirectory", "GetDataObjectDefinition",
                    "DataObjectDirectory", "GetDataSetValue", "DataSetDirectory", "ReadWrite",
                    "GetCBValues"):  # fmt: skip
        ET.SubElement(services, service)
    ET.SubElement(services, "ConfDataSet", max="2", maxAttributes="16")
    ET.SubElement(services, "ConfReportControl", max=str(len(REPORTS)))
    ET.SubElement(services, "ReportSettings", cbName="Fix", datSet="Fix", rptID="Fix",
                  optFields="Fix", bufTime="Fix", trgOps="Fix", intgPd="Fix")  # fmt: skip
    point = ET.SubElement(ied, "AccessPoint", name=ACCESS_POINT)
    server = ET.SubElement(point, "Server")
    ET.SubElement(server, "Authentication", none="true")
    device = ET.SubElement(server, "LDevice", inst=LOGICAL_DEVICE)
    family = "bus" if kind == "bus" else "breaker"
    for node_name in LOGICAL_NODES[kind]:
        if node_name == "LLN0":
            node = ET.SubElement(device, "LN0", lnClass="LLN0", inst="", lnType="LLN0")
            for set_name, members in (("dsEvents", _EVENTS[family]),
                                      ("dsMeas", _MEASUREMENTS[family])):  # fmt: skip
                data_set = ET.SubElement(node, "DataSet", name=set_name)
                for member in members:
                    ln, _, do = member.partition(".")
                    ET.SubElement(
                        data_set, "FCDA", ldInst=LOGICAL_DEVICE, lnClass=ln[:-1], lnInst=ln[-1],
                        doName=do, fc="ST" if set_name == "dsEvents" else "MX",
                    )  # fmt: skip
            for report, buffered, data_set_name in REPORTS:
                control = ET.SubElement(
                    node, "ReportControl", name=report, rptID=f"{name}/{report}",
                    datSet=data_set_name, confRev="1", buffered=str(buffered).lower(),
                    bufTime="0", intgPd="0",
                )  # fmt: skip
                ET.SubElement(control, "TrgOps", dchg="true", qchg="true", gi="true")
                ET.SubElement(control, "OptFields", seqNum="true", timeStamp="true",
                              dataSet="true", reasonCode="true", entryID="true")  # fmt: skip
                ET.SubElement(control, "RptEnabled", max="1")
        else:
            node = ET.SubElement(
                device, "LN", lnClass=node_name[:-1], inst=node_name[-1],
                lnType=ln_type(kind, node_name),
            )  # fmt: skip
        _instance_values(node, node_name, settings)
        if node_name == "LLN0":
            ET.SubElement(node, "SettingControl", numOfSGs="1", actSG="1")


def _document(identifier: str) -> ET.Element:
    root = ET.Element("SCL", xmlns=NAMESPACE, version="2007", revision="B")
    ET.SubElement(
        root, "Header", id=identifier, version="1", revision="A", toolID="agentic-datacenter"
    )
    return root


def _text(root: ET.Element) -> str:
    ET.indent(root, space="  ")
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def scd(relays: Sequence[Relay]) -> str:
    """Return the SCD of the site: every relay, its access point and the shared types."""
    ordered = sorted(relays, key=lambda r: r.tag)
    root = _document("ADC-Z1-MV")
    network = ET.SubElement(
        ET.SubElement(root, "Communication"), "SubNetwork", name=SUBNETWORK, type="8-MMS"
    )
    for relay in ordered:
        # Loopback: in the test job every relay listens there, on a port of its own.
        connected = ET.SubElement(network, "ConnectedAP", iedName=relay.name, apName=ACCESS_POINT)
        ET.SubElement(ET.SubElement(connected, "Address"), "P", type="IP").text = "127.0.0.1"
    for relay in ordered:
        _ied(root, relay.name, relay.tag, relay.kind, dict(relay.settings))
    _templates(root, sorted({r.kind for r in ordered}))
    return _text(root)


def icd(kind: str, relays: Sequence[Relay]) -> str:
    """Return the ICD of relay type *kind*, taken from the first relay of that kind.

    Raises:
        SclError: If no relay of that kind exists.
    """
    example = next((r for r in sorted(relays, key=lambda r: r.tag) if r.kind == kind), None)
    if example is None:
        raise SclError(f"no relay of type {kind!r}")
    settings = {k: v for k, v in example.settings.items() if not k.endswith("NamPlt.d")}
    root = _document(f"ADC-{kind}")
    _ied(root, "TEMPLATE", f"{kind} relay", kind, settings)
    _templates(root, [kind])
    return _text(root)


def export(relays: Sequence[Relay], directory: Path) -> list[Path]:
    """Write the SCD and one ICD per relay type into *directory*; return the paths."""
    directory.mkdir(parents=True, exist_ok=True)
    files = {"site.scd": scd(relays)}
    for kind in sorted({r.kind for r in relays}):
        files[f"{kind}.icd"] = icd(kind, relays)
    out = []
    for name, text in sorted(files.items()):
        path = directory / name
        path.write_text(text, encoding="utf-8")
        out.append(path)
    return out


# -- reading ---------------------------------------------------------------------------------


def _q(name: str) -> str:
    return f"{{{NAMESPACE}}}{name}"


class _Types:
    def __init__(self, templates: ET.Element) -> None:
        self.by_id = {str(e.get("id")): e for e in templates}

    def ordinal(self, enum: str, literal: str) -> int:
        for value in self.by_id[enum]:
            if (value.text or "") == literal:
                return int(str(value.get("ord")))
        raise SclError(f"{literal!r} is not a value of {enum}")

    def leaves(
        self, element: ET.Element, ref: str, fc: str, depth: int, trigger: str,
        given: dict[str, str],
    ) -> list[Leaf]:  # fmt: skip
        """Return the basic attributes under *element* (a DO, SDO, DA or BDA)."""
        out: list[Leaf] = []
        if element.tag in (_q("DO"), _q("SDO")):
            for member in self.by_id[str(element.get("type"))]:
                if member.tag == _q("SDO"):
                    path = f"{ref}.{member.get('name')}"
                    out += self.leaves(member, path, "", depth + 1, "", given)
                else:
                    kind = "dchg" if member.get("dchg") else ("qchg" if member.get("qchg") else "")
                    path = f"{ref}.{member.get('name')}"
                    out += self.leaves(member, path, str(member.get("fc")), depth, kind, given)
            return out
        btype = str(element.get("bType"))
        if btype == "Struct":
            for member in self.by_id[str(element.get("type"))]:
                out += self.leaves(member, f"{ref}.{member.get('name')}", fc, depth, trigger, given)
            return out
        default = element.find(_q("Val"))
        value = given.get(ref, (default.text or "") if default is not None else "")
        ordinal = None
        if btype == "Enum" and (ref in given or default is not None):
            ordinal = self.ordinal(str(element.get("type")), value)
        return [Leaf(ref, fc, btype, depth, trigger, value, ordinal)]


def _given(node: ET.Element, ref: str, out: dict[str, str]) -> None:
    for child in node:
        if child.tag in (_q("DOI"), _q("SDI")):
            _given(child, f"{ref}.{child.get('name')}", out)
        elif child.tag == _q("DAI"):
            value = child.find(_q("Val"))
            out[f"{ref}.{child.get('name')}"] = (value.text or "") if value is not None else ""


def parse(text: str) -> list[Ied]:
    """Read an SCD or ICD written by this module.

    Raises:
        SclError: If the text is not such a file.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise SclError(f"not XML: {exc}") from exc
    templates = root.find(_q("DataTypeTemplates"))
    if root.tag != _q("SCL") or templates is None:
        raise SclError("not an SCL file with data type templates")
    types = _Types(templates)
    out = []
    for ied in root.findall(_q("IED")):
        name = str(ied.get("name"))
        device = ied.find(f"{_q('AccessPoint')}/{_q('Server')}/{_q('LDevice')}")
        if device is None:
            raise SclError(f"{name}: no logical device")
        inst = str(device.get("inst"))
        nodes: list[str] = []
        leaves: list[Leaf] = []
        data_sets: list[DataSet] = []
        reports: list[Report] = []
        groups = (1, 1)
        for node in device:
            node_name = f"{node.get('lnClass')}{node.get('inst')}"
            nodes.append(node_name)
            base = f"{inst}/{node_name}"
            given: dict[str, str] = {}
            _given(node, base, given)
            for data in types.by_id[str(node.get("lnType"))]:
                leaves += types.leaves(data, f"{base}.{data.get('name')}", "", 1, "", given)
            for data_set in node.findall(_q("DataSet")):
                members = tuple(
                    f"{m.get('ldInst')}/{m.get('lnClass')}{m.get('lnInst')}"
                    f".{m.get('doName')}[{m.get('fc')}]"
                    for m in data_set
                )
                data_sets.append(DataSet(str(data_set.get("name")), members))
            for control in node.findall(_q("ReportControl")):
                enabled = control.find(_q("RptEnabled"))
                count = int(str(enabled.get("max"))) if enabled is not None else 1
                for index in range(1, count + 1):
                    reports.append(
                        Report(
                            f"{control.get('name')}{index:02d}",
                            control.get("buffered") == "true",
                            str(control.get("datSet")),
                            str(control.get("rptID")),
                        )
                    )
            setting = node.find(_q("SettingControl"))
            if setting is not None:
                groups = (int(str(setting.get("actSG"))), int(str(setting.get("numOfSGs"))))
        out.append(
            Ied(name, str(ied.get("desc")), str(ied.get("type")), tuple(nodes), tuple(leaves),
                tuple(data_sets), tuple(reports), groups)
        )  # fmt: skip
    return out
