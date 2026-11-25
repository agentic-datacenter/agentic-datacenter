# SPDX-License-Identifier: MIT
"""A governance gate served over HTTP, for Agentic-Datacenter's ``http_gate`` binding.

Standard library only. Replace ``decide`` with a call into your own system;
everything else is the wire format (``agentic_datacenter.gate.http/1``).

    python examples/http-gate/server.py --port 8787
    ADC_GATE_URL=http://127.0.0.1:8787 ADC_GATE_NAME=example agentic-datacenter gate check http_gate

The policy below is an example, not a recommendation: it refuses what cannot
be formed or exceeds a bound or limit, abstains when a premise cannot be
established, asks a person when the contract says so, and allows the rest.
"""

from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

SCHEMA = "agentic_datacenter.gate.http/1"


def no_mandate(request: dict[str, Any]) -> str:
    """Say which kind of no mandate the proposer has, from the mandate record alone.

    ``mandate`` is in the request once a mandate was set for the proposer: every
    change, oldest first, and the last one is in force. ``ended`` when an earlier
    change held this contract, ``never_held`` when none did, and nothing when
    the mandate holds or there is no record.
    """
    record = request.get("mandate")
    if not record:
        return ""
    contract, changes = request["proposal"]["contract_id"], record["changes"]
    if contract in changes[-1]["contracts"]:
        return ""
    return "ended" if any(contract in c["contracts"] for c in changes[:-1]) else "never_held"


def decide(request: dict[str, Any]) -> dict[str, Any]:
    """Return the answer to one ``evaluate`` request. Must be deterministic."""
    premises = request["premises"]
    refusals = list(premises["schema_errors"]) + list(premises["bound_errors"])
    refusals += list(premises["limit_errors"])
    if not premises["contract_known"]:
        refusals.insert(0, "unknown contract")
    unknown = [p["expr"] for p in premises["premises"] if p["holds"] is None]
    failed = [p["expr"] for p in premises["premises"] if p["holds"] is False]
    # Who may act. The premise authority(<principal>, <contract>) says it, and so
    # does the mandate record. A service started with ADC_GATE_DERIVES_AUTHORITY=1
    # is sent the record alone, so this one decides from the record and reads
    # the premise only when there is no record.
    kind = no_mandate(request)
    no_authority = bool(kind) or any(e.startswith("authority(") for e in failed)
    if kind and not any(e.startswith("authority(") for e in failed):
        failed.append(f"the mandate record: {kind}")
    # Why, in a word, for every way the step is wrong, not only the first found.
    codes = [
        code
        for code, applies in (
            ("authority", no_authority),
            ("limit", bool(premises["bound_errors"] or premises["limit_errors"])),
            (
                "premise",
                any(not e.startswith(("authority(", "the mandate record")) for e in failed),
            ),
            ("evidence", bool(unknown)),
            ("malformed", bool(premises["schema_errors"]) or not premises["contract_known"]),
        )
        if applies
    ]
    more: dict[str, Any] = {}
    if request.get("mandate"):
        # Optional: this gate's own finding, compared with the premise on the card.
        more["authority_holds"] = not kind
    if kind:
        # Optional: which of the two kinds of no mandate the refusal is for.
        more["reason_details"] = {"authority": kind}
    if refusals:
        return {"verdict": "DENY", "reasons": refusals, "reason_codes": codes, **more}
    if unknown:
        return {"verdict": "ABSTAIN", "reasons": [f"cannot establish: {e}" for e in unknown],
                "reason_codes": codes, **more}  # fmt: skip
    if failed:
        return {"verdict": "DENY", "reasons": [f"premise does not hold: {e}" for e in failed],
                "reason_codes": codes, **more}  # fmt: skip
    if premises["approval"] in ("one_operator", "two_person"):
        approvers = 2 if premises["approval"] == "two_person" else 1
        return {"verdict": "VERIFY", "reasons": ["contract requires approval"],
                "required_approvers": approvers, "reason_codes": ["approval"], **more}  # fmt: skip
    if premises["approval"] == "not_available":
        return {"verdict": "DENY", "reasons": ["contract cannot be approved here"],
                "reason_codes": ["policy"], **more}  # fmt: skip
    return {"verdict": "ALLOW", "reasons": ["premises hold; within bounds and limits"], **more}


class Handler(BaseHTTPRequestHandler):
    """Answers ``POST /evaluate`` and ``POST /outcome``."""

    def do_POST(self) -> None:  # noqa: N802 - the name http.server calls
        """Read one JSON request and answer it."""
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
        if body.get("schema") != SCHEMA:
            self._send(400, {"schema": SCHEMA, "error": "unknown schema"})
        elif self.path == "/evaluate":
            self._send(200, {"schema": SCHEMA, **decide(body)})
        elif self.path == "/outcome":
            self._send(200, {"schema": SCHEMA})
        else:
            self._send(404, {"schema": SCHEMA, "error": "not found"})

    def _send(self, status: int, answer: dict[str, Any]) -> None:
        data = json.dumps(answer).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002
        """Stay quiet; a benchmark makes many requests."""


def main() -> None:
    """Serve on loopback until interrupted."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--port", type=int, default=8787)
    args = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"serving {SCHEMA} on http://127.0.0.1:{args.port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
