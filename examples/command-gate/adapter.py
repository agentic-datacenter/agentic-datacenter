# SPDX-License-Identifier: MIT
"""A stateless, standard-library starter for the command gate interface.

With ``ADC_RECEIPTS_FILE`` set it also writes a receipt line per decision and
per outcome, keyed by the ``correlation_id`` both messages carry, as a system
that issues receipts would. ``agentic-datacenter gate verify-receipts`` checks
them against the run. With ``ADC_GATE_CONTEXT=1`` the request carries a
read-only sample of the plant, and the starter refuses a step while an
interlock is locked out.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

SCHEMA = "agentic_datacenter.gate.http/1"
APPROVERS = {"one_operator": 1, "two_person": 2}


def decide(request: dict[str, Any]) -> dict[str, Any]:
    """Translate the supplied simulated premises into a decision."""
    context = request.get("context")
    if isinstance(context, dict):
        locked = [
            p["tag"] for p in context.get("interlocks", [])
            if p["tag"].endswith(".alarm_lockout") and p["value"] is True
        ]  # fmt: skip
        if locked:
            return answer("DENY", [f"interlock locked out: {locked[0]}"], "premise")
    premises = request["premises"]
    for field, code in (
        ("schema_errors", "malformed"),
        ("bound_errors", "limit"),
        ("limit_errors", "limit"),
    ):
        if errors := premises[field]:
            return answer("DENY", list(errors), code)
    if not premises["contract_known"] or not premises["writes"]:
        return answer("DENY", ["no valid bounded write"], "malformed")

    checks = premises["premises"]
    if any(check["holds"] is False for check in checks):
        return answer("DENY", ["a required premise failed"], "premise")
    if any(check["holds"] is not True for check in checks):
        return answer("ABSTAIN", ["a required premise is unavailable"], "evidence")

    approval = premises["approval"]
    if approval in APPROVERS:
        return {
            **answer("VERIFY", ["this contract requires human approval"], "approval"),
            "required_approvers": APPROVERS[approval],
        }
    if approval != "none":
        return answer("ABSTAIN", ["approval requirement is unavailable"], "approval")
    return answer("ALLOW", ["the example policy accepted the proposed writes"], "policy")


def answer(verdict: str, reasons: list[str], code: str) -> dict[str, Any]:
    """Return the common answer envelope."""
    return {"schema": SCHEMA, "verdict": verdict, "reasons": reasons, "reason_codes": [code]}


def receipt(line: dict[str, Any]) -> None:
    """Append one receipt line to ``ADC_RECEIPTS_FILE``, if it is set."""
    path = os.environ.get("ADC_RECEIPTS_FILE")
    if path:
        with open(path, "a", encoding="utf-8") as out:
            out.write(json.dumps(line, sort_keys=True) + "\n")


def main() -> int:
    """Read one request and return one JSON decision on standard output."""
    try:
        envelope = json.load(sys.stdin)
        request = envelope["request"]
        if request["schema"] != SCHEMA:
            raise ValueError("unsupported request schema")
        endpoint = envelope["endpoint"]
        if endpoint == "/outcome":
            if "correlation_id" in request:
                receipt({"correlation_id": request["correlation_id"], "outcome": request["status"]})
            return 0
        if endpoint != "/evaluate":
            raise ValueError("unsupported endpoint")
        decision = decide(request)
        tie = request.get("correlation") or {}
        if tie:
            decision["decision_id"] = "example-" + tie["action_ref"][7:19]
            receipt({
                "correlation_id": tie["correlation_id"], "action_ref": tie["action_ref"],
                "verdict": decision["verdict"], "decision_id": decision["decision_id"],
            })  # fmt: skip
        print(json.dumps(decision, sort_keys=True))
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        print(f"adapter request error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
