# SPDX-License-Identifier: MIT
"""A stateless, standard-library starter for the command gate interface."""

from __future__ import annotations

import json
import sys
from typing import Any

SCHEMA = "agentic_datacenter.gate.http/1"
APPROVERS = {"one_operator": 1, "two_person": 2}


def decide(request: dict[str, Any]) -> dict[str, Any]:
    """Translate the supplied simulated premises into a decision."""
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


def main() -> int:
    """Read one request and return one JSON decision on standard output."""
    try:
        envelope = json.load(sys.stdin)
        request = envelope["request"]
        if request["schema"] != SCHEMA:
            raise ValueError("unsupported request schema")
        endpoint = envelope["endpoint"]
        if endpoint == "/outcome":
            return 0
        if endpoint != "/evaluate":
            raise ValueError("unsupported endpoint")
        print(json.dumps(decide(request), sort_keys=True))
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        print(f"adapter request error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
