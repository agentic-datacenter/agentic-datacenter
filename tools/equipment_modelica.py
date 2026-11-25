"""Make equipment registry entries from chiller records of the Modelica Buildings Library.

Reads ``Buildings/Fluid/Chillers/Data/ElectricEIR.mo`` at the commit pinned in
``equipment/sources.yaml`` and writes one entry per named record into
``equipment/cooling.chw_plant/``. Each value it takes cites the line it was read
from. Nothing of the source file is copied but the facts it states (ADR 0034).

    python tools/equipment_modelica.py <ElectricEIR.mo> <record> [<record> ...]
    python tools/equipment_modelica.py <ElectricEIR.mo> --check

``--check`` derives every entry again from the file and fails on any
difference. The file is fetched at the pinned commit with::

    gh api "repos/lbl-srg/modelica-buildings/contents/$FILE?ref=<commit>" --jq .content \
        | base64 -d

with ``FILE=Buildings/Fluid/Chillers/Data/ElectricEIR.mo``.
"""

from __future__ import annotations

import hashlib
import re
import sys
from pathlib import Path
from typing import Any

import yaml

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "equipment" / "cooling.chw_plant"
SOURCE_ID = "modelica-buildings"
SOURCE_PATH = "Buildings/Fluid/Chillers/Data/ElectricEIR.mo"
FIELDS = ("QEva_flow_nominal", "COP_nominal", "PLRMin", "TEvaLvg_nominal", "TConEnt_nominal")
_NAME = re.compile(r"^ElectricEIRChiller_([A-Za-z]+)_([A-Za-z0-9]+)_(.+)$")


def _number(text: str) -> float:
    text = text.strip().rstrip(",").rstrip(")")
    if "*" in text:
        a, b = text.split("*")
        return float(a) * float(b)
    if "+" in text:
        a, b = text.split("+")
        return float(a) + float(b)
    return float(text)


def read_record(lines: list[str], name: str) -> dict[str, Any]:
    """Return the values of one record and the line each was read from (1-based)."""
    start = next((i for i, line in enumerate(lines) if line.strip() == f"record {name} ="), None)
    if start is None:
        raise SystemExit(f"no record {name} in the file")
    values: dict[str, tuple[float, int]] = {}
    description = None
    for i in range(start + 1, min(start + 40, len(lines))):
        line = lines[i].strip()
        for field in FIELDS:
            if "=" in line and line.split("=", 1)[0].strip() == field:
                values[field] = (_number(line.split("=", 1)[1]), i + 1)
        match = re.match(r'^"(.+)" annotation', line)
        if match:
            description = (match.group(1), i + 1)
            break
    missing = [f for f in FIELDS if f not in values]
    if missing or description is None:
        raise SystemExit(f"{name}: could not read {missing or ['its description']}")
    return {"name": name, "start": start + 1, "values": values, "description": description}


def entry(record: dict[str, Any], commit: str) -> dict[str, Any]:
    """Return the registry entry of one record."""
    name = record["name"]
    match = _NAME.match(name)
    if match is None:
        raise SystemExit(f"{name}: not a record named after a maker and model")
    maker, model, variant = match.groups()
    v = record["values"]

    def cite(field: str) -> str:
        return f"{SOURCE_ID} {SOURCE_PATH}:{v[field][1]} {field} (commit {commit[:12]})"

    capacity_kw = round(-v["QEva_flow_nominal"][0] / 1000.0, 3)
    return {
        "id": f"modelica.{maker.lower()}_{model.lower()}_{variant.lower()}",
        "module": "cooling.chw_plant",
        "maker": maker,
        "model": model,
        "variant": variant,
        "tier": "factual",
        "params": {
            "chiller_kw": {"value": capacity_kw, "unit": "kW", "source": cite("QEva_flow_nominal")},
            "cop": {"value": v["COP_nominal"][0], "unit": "-", "source": cite("COP_nominal")},
        },
        "rated_conditions": {
            "chilled_water_leaving_c": round(v["TEvaLvg_nominal"][0] - 273.15, 2),
            "condenser_entering_c": round(v["TConEnt_nominal"][0] - 273.15, 2),
            "part_load_ratio_min": v["PLRMin"][0],
        },
        "fit": (
            "The record describes a water-cooled chiller at the rated conditions above. "
            "cooling.chw_plant models an air-cooled plant of identical chillers: only the rated "
            "capacity and COP are taken, and the module's own curves apply to them. The COP was "
            f"rated with condenser water entering at {round(v['TConEnt_nominal'][0] - 273.15, 2)} "
            "degC; the module applies it at its design ambient air temperature, so the plant's "
            "efficiency is likely higher than an air-cooled chiller of the same capacity reaches."
        ),
        "provenance": {
            "source": SOURCE_ID,
            "record": name,
            "description": record["description"][0],
            "lines": [record["start"], record["description"][1]],
            "data_type": "factual_specification",
            "redistributes_source_document": False,
            "derived_from": (
                "the EnergyPlus Chiller:Electric:EIR object embedded in the record, which the "
                "record names as its origin"
            ),
        },
        "simulation": {
            "model_origin": "independently_developed",
            "manufacturer_validated": False,
            "calibration": "uncalibrated",
        },
        "rights": {
            "commercial_use": "allowed",
            "redistribution": "allowed",
            "basis": (
                "facts stated in a file under the BSD-3-Clause-style licence of the Modelica "
                "Buildings Library, kept with attribution "
                "(equipment/licences/modelica-buildings.txt)"
            ),
            "reviewed": "2026-11-24",
        },
    }


def _write(path: Path, data: dict[str, Any]) -> str:
    text = "# Made by tools/equipment_modelica.py; do not edit by hand.\n" + yaml.safe_dump(
        data, sort_keys=False, allow_unicode=False, width=100
    )
    return text


def main(argv: list[str]) -> int:
    """Write or check the entries; return the exit status."""
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    source = Path(argv[0])
    raw = source.read_bytes()
    sources = yaml.safe_load((REPO / "equipment" / "sources.yaml").read_text(encoding="utf-8"))
    pinned = sources[SOURCE_ID]
    if hashlib.sha256(raw).hexdigest() != pinned["files"][SOURCE_PATH]:
        print(f"{source} is not {SOURCE_PATH} at the pinned commit", file=sys.stderr)
        return 1
    lines = raw.decode("utf-8").splitlines()
    if argv[1] == "--check":
        problems = 0
        for path in sorted(OUT.glob("modelica.*.yaml")):
            record = yaml.safe_load(path.read_text(encoding="utf-8"))["provenance"]["record"]
            text = _write(path, entry(read_record(lines, record), pinned["commit"]))
            if path.read_text(encoding="utf-8") != text:
                print(f"{path.name} differs from what the source gives", file=sys.stderr)
                problems += 1
        return 1 if problems else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for name in argv[1:]:
        data = entry(read_record(lines, name), pinned["commit"])
        path = OUT / f"{data['id']}.yaml"
        path.write_text(_write(path, data), encoding="utf-8")
        print(f"wrote {path.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
