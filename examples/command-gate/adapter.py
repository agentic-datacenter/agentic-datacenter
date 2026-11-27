# SPDX-License-Identifier: MIT
"""A stateless, standard-library starter for the command gate interface.

With ``ADC_RECEIPTS_FILE`` set it also writes a receipt line per decision and
per outcome, keyed by the ``correlation_id`` both messages carry, as a system
that issues receipts would. ``agentic-datacenter gate verify-receipts`` checks
them against the run. With ``ADC_GATE_CONTEXT=1`` the request carries a
read-only sample of the plant, and the starter refuses a step while an
interlock is locked out.

Two more things, each of which needs the ``cryptography`` package and is off
unless asked for:

- ``ADC_VERIFY_READINGS=1``: each reading of the context is signed by its
  source. A reading that does not verify is left out before anything is
  decided on it, so a false reading put in on the network stops nothing.
- ``ADC_RECEIPTS_KEY_SEED``: 64 hexadecimal digits, the seed of an Ed25519 key
  of your own. Each receipt is then signed, over the receipt without its
  signature as canonical JSON. ``--public-key`` prints the public half, to give
  to ``ADC_GATE_RECEIPT_KEY`` and to ``gate verify-receipts --key``.
"""

from __future__ import annotations

import json
import os
import sys
from typing import Any

SCHEMA = "agentic_datacenter.gate.http/1"
APPROVERS = {"one_operator": 1, "two_person": 2}
SIGNED_OF_A_READING = ("tag", "value", "unit", "quality", "time_ms")


def verifies(row: dict[str, Any], sources: list[dict[str, Any]]) -> bool:
    """Whether a reading was signed by the source it names, and says what was signed."""
    import base64  # noqa: PLC0415 - only when readings are verified

    from cryptography.exceptions import InvalidSignature  # noqa: PLC0415
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: PLC0415
        Ed25519PublicKey,
    )

    source = next((s for s in sources if s["name"] == row.get("source")), None)
    signature, text = row.get("signature"), row.get("reading")
    if source is None or not isinstance(signature, dict) or not isinstance(text, str):
        return False
    if signature.get("key_id") != source["key_id"]:
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(source["public_key"]))
        key.verify(base64.b64decode(signature["value"]), text.encode("utf-8"))
    except (InvalidSignature, ValueError, KeyError):
        return False
    said = json.loads(text)
    return all(said.get(name) == row.get(name) for name in SIGNED_OF_A_READING)


def signing_key() -> Any:
    """Return the key receipts are signed with, or None when no seed was given."""
    seed = os.environ.get("ADC_RECEIPTS_KEY_SEED")
    if not seed:
        return None
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (  # noqa: PLC0415
        Ed25519PrivateKey,
    )

    return Ed25519PrivateKey.from_private_bytes(bytes.fromhex(seed))


def signed(receipt_line: dict[str, Any]) -> dict[str, Any]:
    """Return a receipt with its signature, when a key seed was given; else as it is."""
    key = signing_key()
    if key is None:
        return receipt_line
    import base64  # noqa: PLC0415
    import hashlib  # noqa: PLC0415

    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: PLC0415

    covered = json.dumps(
        receipt_line, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    public = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return {
        **receipt_line,
        "signature": {
            "alg": "Ed25519",
            "key_id": "sha256:" + hashlib.sha256(public).hexdigest(),
            "value": base64.b64encode(key.sign(covered)).decode("ascii"),
        },
    }


def decide(request: dict[str, Any]) -> dict[str, Any]:
    """Translate the supplied simulated premises into a decision."""
    context = request.get("context")
    if isinstance(context, dict):
        interlocks = context.get("interlocks", [])
        if os.environ.get("ADC_VERIFY_READINGS") == "1":
            interlocks = [p for p in interlocks if verifies(p, context.get("sources", []))]
        locked = [
            p["tag"] for p in interlocks
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
            out.write(json.dumps(signed(line), sort_keys=True) + "\n")


def main() -> int:
    """Read one request and return one JSON decision on standard output."""
    if sys.argv[1:] == ["--public-key"]:
        import base64  # noqa: PLC0415

        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat  # noqa: PLC0415

        key = signing_key()
        if key is None:
            print("set ADC_RECEIPTS_KEY_SEED first", file=sys.stderr)
            return 1
        raw = key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
        print(base64.b64encode(raw).decode("ascii"))
        return 0
    try:
        envelope = json.load(sys.stdin)
        request = envelope["request"]
        if request["schema"] != SCHEMA:
            raise ValueError("unsupported request schema")
        endpoint = envelope["endpoint"]
        if endpoint == "/outcome":
            if request.get("correlation_id"):
                receipt({"correlation_id": request["correlation_id"], "outcome": request["status"]})
            return 0
        if endpoint != "/evaluate":
            raise ValueError("unsupported endpoint")
        decision = decide(request)
        tie = request.get("correlation") or {}
        if tie:
            decision["decision_id"] = "example-" + tie["action_ref"][7:19]
            line = {
                "correlation_id": tie["correlation_id"], "action_ref": tie["action_ref"],
                "verdict": decision["verdict"], "decision_id": decision["decision_id"],
            }  # fmt: skip
            receipt(line)
            if signing_key() is not None:
                # The same receipt, signed, with the answer: checked at once when
                # the run was given the public key (ADC_GATE_RECEIPT_KEY).
                decision["receipt"] = signed(line)
        print(json.dumps(decision, sort_keys=True))
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        print(f"adapter request error: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
