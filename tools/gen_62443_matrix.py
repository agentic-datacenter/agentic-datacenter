"""Generate the IEC 62443-3-3 matrix from test results (ADC-EVD-002).

The matrix of section 4.3 pairs each group of system requirements with the
mechanism in Agentic-Datacenter and the requirements whose tests are the evidence.
This tool reads the requirement report of a test run (``pytest --req-report``)
and writes the matrix with what that run showed. Nothing in the output is
typed by hand: the status of a row is computed, and the page carries the hash
of the report it was made from.

It claims no certification and no conformance. It says which mechanisms have
passing tests in this simulator.

Where a row credits REMORA with a capability, the tool names the capability by
its id in REMORA's capability register and nothing more. The name and the
maturity word are read from the register of the pinned, installed REMORA and
reproduced unchanged (ADC-PIN-006). Without REMORA the matrix credits it with
nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import sys
from collections.abc import Mapping
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]

#: Foundational requirement -> (system requirements, mechanism, requirements as
#: evidence, the gate's role). SR numbers only; no text of the standard is reproduced.
ROWS: tuple[tuple[str, str, str, tuple[str, ...], str], ...] = (
    (
        "FR 1 Identification and authentication",
        "SR 1.1, 1.2, 1.3, 1.8, 1.11, 1.13",
        "Named operator accounts with roles; sessions; identity of the agent taken from its "
        "credential",
        ("ADC-SUP-004", "ADC-GOV-001"),
        "Agent authenticated as a software process",
    ),
    (
        "FR 2 Use control",
        "SR 2.1 (RE 1, 2, 4), 2.5, 2.6, 2.8, 2.9, 2.10, 2.11, 2.12",
        "Four permission levels; revert to view-only after 15 min; change log and audit log",
        ("ADC-SUP-003", "ADC-SUP-004", "ADC-SUP-005", "ADC-GOV-002", "ADC-GOV-005"),
        "Authorization for every agent action; approval for high-risk tiers; decision records",
    ),
    (
        "FR 3 System integrity",
        "SR 3.1, 3.4, 3.5, 3.6, 3.7, 3.9",
        "Point-schema validation of every write; append-only logs; controllers fall to defined "
        "states",
        ("ADC-SUP-002", "ADC-SUP-005", "ADC-GOV-003", "ADC-GOV-006"),
        "Typed intent contracts validate inputs",
    ),
    (
        "FR 4 Data confidentiality",
        "SR 4.1, 4.3",
        "TLS on conduits C2 to C5; legacy protocols stay inside level 1 and 2 zones",
        (),
        "n/a",
    ),
    (
        "FR 5 Restricted data flow",
        "SR 5.1, 5.2, 5.4",
        "Zone network model; conduit allowlists; deny by default",
        ("ADC-NET-001", "ADC-NET-002", "ADC-NET-004"),
        "The gate is the boundary protection device for C4 and C5",
    ),
    (
        "FR 6 Timely response to events",
        "SR 6.1, 6.2",
        "Conduit violation events; append-only alarm and audit logs",
        ("ADC-NET-003", "ADC-SUP-001", "ADC-SUP-002"),
        "Denials and abstentions recorded as decisions",
    ),
    (
        "FR 7 Resource availability",
        "SR 7.1, 7.2, 7.3, 7.4, 7.6, 7.7",
        "Rate limits on supervisory writes; controller autonomy on network loss; snapshot and "
        "restore of simulator state",
        ("ADC-SUP-005", "ADC-CTL-003", "ADC-KRN-002"),
        "Per-contract rate and cumulative limits",
    ),
)
STATEMENTS = (
    "This matrix is generated from one test run of a simulator. It is not a certificate and "
    "claims no conformance to IEC 62443.",
    "Treating an AI agent as a software process under SR 1.2 and SR 2.1 is this project's "
    "interpretation, not a requirement of the standard.",
    "Requirement-enhancement numbers and the security level at which each requirement applies "
    "have not been checked against the standard text.",
    "Modbus/TCP and BACnet/IP carry no authentication; the zone boundary is the compensating "
    "countermeasure.",
    "A passing test shows a mechanism under that test's own conditions. A requirement is "
    "closed only when its stage is (see the traceability report). ADC-GOV-001 is not closed "
    "without the GOVERNED profile, whatever this page shows for the tests marked with it.",
    "The role of the gate is stated as the design intends it, for any gate under test. It "
    "says nothing about how far a gate has come. Where REMORA is credited with a capability, "
    "in the last table, the maturity word is REMORA's own.",
)
#: Foundational requirement -> the capabilities of REMORA that the governed binding uses
#: for the gate's role in that row, by their ids in REMORA's capability register. Ids only:
#: the name and the maturity word of each are read from the register (ADC-PIN-006).
REMORA_CREDIT: dict[str, tuple[str, ...]] = {
    "FR 2": ("CAP-001", "CAP-005", "CAP-007"),
    "FR 3": ("CAP-004",),
    "FR 6": ("CAP-005",),
    "FR 7": ("CAP-031",),
}


def remora_register(pin_file: Path) -> Any:
    """Return REMORA's capability register at the pin, or None when REMORA is not installed.

    Raises:
        RuntimeError: If REMORA is installed and is not the pinned commit, or carries no
            register. A matrix with words from another commit is never written.
    """
    try:
        module = importlib.import_module("agentic_datacenter_remora.register")
    except ImportError:
        return None
    return module.capability_register(pin_file)


def credit(register: Any) -> list[str]:
    """Return the section that says which capabilities of REMORA the matrix credits."""
    lines = ["", "## REMORA capabilities credited", ""]
    if register is None:
        return [
            *lines,
            "None. This matrix was made without REMORA installed, so it credits REMORA with "
            "no capability and states no maturity.",
        ]
    lines += [
        f"Read from REMORA's capability register as the installed package carries it: commit "
        f"`{register.commit}`, file `{register.file}` (`sha256:{register.sha256}`), which REMORA "
        f"builds from `{register.source}`.",
        "",
        "- The name and the maturity word of each capability are REMORA's own, unchanged. The "
        "words are REMORA's ladder, and it explains them in its register.",
        "- Which capability is named for a row is this project's reading of what the governed "
        "binding uses. It has not been confirmed by the REMORA maintainer.",
        "- A row that is not listed credits REMORA with nothing.",
        "",
        "| Foundational requirement | Capability | Name in the register | Maturity in the register "
        "|",
        "| --- | --- | --- | --- |",
    ]
    for name, _, _, _, _ in ROWS:
        for capability_id in REMORA_CREDIT.get(name[:4], ()):
            entry = register.capability(capability_id)
            shown = entry.name.replace("|", "\\|")  # a bar would end the table cell
            lines.append(f"| {name} | `{entry.id}` | {shown} | `{entry.status}` |")
    return lines


def status(requirement: str, report: Mapping[str, Mapping[str, list[str]]]) -> str:
    """Return what the test run showed for one Agentic-Datacenter requirement."""
    entry = report.get(requirement, {})
    passed, failed = len(entry.get("passed", [])), len(entry.get("failed", []))
    if failed:
        return f"{failed} failing"
    return f"{passed} passing" if passed else "no test"


def render(
    report: Mapping[str, Mapping[str, list[str]]], report_hash: str, register: Any = None
) -> str:
    """Return the matrix as Markdown.

    *register* is REMORA's capability register (``remora_register``), or None
    for a matrix that credits REMORA with nothing.
    """
    lines = [
        "<!-- Generated by tools/gen_62443_matrix.py from a test run. Do not edit. -->",
        "",
        "# IEC 62443-3-3 mechanisms and their evidence",
        "",
        *(f"- {s}" for s in STATEMENTS),
        "",
        f"Requirement report: `sha256:{report_hash}`",
        "",
        "| Foundational requirement | System requirements | Mechanism in Agentic-Datacenter "
        "| Evidence | Result of this run | Role of the gate |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for name, srs, mechanism, evidence, gate in ROWS:
        shown = [f"`{r}`: {status(r, report)}" for r in evidence]
        states = [status(r, report) for r in evidence]
        if not evidence:
            result = "no evidence in the simulator yet"
        elif any(s.endswith("failing") for s in states):
            result = "failing"
        elif all(s.endswith("passing") for s in states):
            result = "all listed tests passing"
        elif any(s.endswith("passing") for s in states):
            result = "partly shown"
        else:
            result = "not shown"
        lines.append(
            f"| {name} | {srs} | {mechanism} | {'<br>'.join(shown) or 'none'} | {result} | {gate} |"
        )
    return "\n".join(lines + credit(register)) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write the matrix for the requirement report given on the command line."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument(
        "--remora-pin", type=Path, default=REPO / "REMORA_PIN",
        help="The pin the installed REMORA must be at for its register to be read.",
    )  # fmt: skip
    args = parser.parse_args(argv)
    raw = args.report.read_bytes()
    try:
        register = remora_register(args.remora_pin)
    except RuntimeError as exc:
        print(f"gen_62443_matrix: {exc}", file=sys.stderr)
        return 1
    text = render(json.loads(raw), hashlib.sha256(raw).hexdigest(), register)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(text, encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
