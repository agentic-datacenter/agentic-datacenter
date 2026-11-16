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


def decide(request: dict[str, Any]) -> dict[str, Any]:
    """Return the answer to one ``evaluate`` request. Must be deterministic."""
    premises = request["premises"]
    refusals = list(premises["schema_errors"]) + list(premises["bound_errors"])
    refusals += list(premises["limit_errors"])
    if not premises["contract_known"]:
        refusals.insert(0, "unknown contract")
    if refusals:
        return {"verdict": "DENY", "reasons": refusals}
    unknown = [p["expr"] for p in premises["premises"] if p["holds"] is None]
    if unknown:
        return {"verdict": "ABSTAIN", "reasons": [f"cannot establish: {e}" for e in unknown]}
    failed = [p["expr"] for p in premises["premises"] if p["holds"] is False]
    if failed:
        return {"verdict": "DENY", "reasons": [f"premise does not hold: {e}" for e in failed]}
    if premises["approval"] in ("one_operator", "two_person"):
        approvers = 2 if premises["approval"] == "two_person" else 1
        return {"verdict": "VERIFY", "reasons": ["contract requires approval"],
                "required_approvers": approvers}  # fmt: skip
    if premises["approval"] == "not_available":
        return {"verdict": "DENY", "reasons": ["contract cannot be approved here"]}
    return {"verdict": "ALLOW", "reasons": ["premises hold; within bounds and limits"]}


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
