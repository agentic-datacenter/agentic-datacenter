# SPDX-License-Identifier: MIT
"""Work out who may act from signed mandate statements.

A reference to copy or to port: the whole rule is ``current`` below, and
``docs/reference/mandate-statements.md`` says the same in words. It shares no
code with Agentic-Datacenter and needs only the ``cryptography`` package.

    python examples/mandate-verifier/verify.py docs/reference/mandate-vectors.json

runs the test vectors, the same ones your own implementation should pass.
With ``--request FILE`` it reads one ``evaluate`` request of the wire format
and prints what the statements in it establish for that proposal.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import sys
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCHEMA = "agentic_datacenter.mandate/1"
SIGNED = (
    "schema", "principal", "contracts", "issuer", "issued_at_ms", "expires_at_ms",
    "supersedes", "reason",
)  # fmt: skip


def signed_bytes(statement: dict[str, Any]) -> bytes:
    """Return what is signed and addressed: the body as canonical JSON.

    Keys sorted, no whitespace, UTF-8, no escaping of non-ASCII characters. The
    body holds only strings, integers, null and lists of strings.
    """
    body = {name: statement.get(name) for name in SIGNED}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def counts(
    statement: dict[str, Any], principal: str, issuers: list[dict[str, Any]], now_ms: int
) -> bool:
    """Rule 1: whether *statement* counts. One that does not is ignored."""
    if statement.get("schema") != SCHEMA or statement.get("principal") != principal:
        return False
    contracts, issued = statement.get("contracts"), statement.get("issued_at_ms")
    expires = statement.get("expires_at_ms")
    if not isinstance(contracts, list) or not all(isinstance(c, str) for c in contracts):
        return False
    if type(issued) is not int or (expires is not None and type(expires) is not int):
        return False
    if statement.get("id") != "sha256:" + hashlib.sha256(signed_bytes(statement)).hexdigest():
        return False
    issuer = next((i for i in issuers if i.get("name") == statement.get("issuer")), None)
    signature = statement.get("signature")
    if issuer is None or not isinstance(signature, dict) or signature.get("alg") != "Ed25519":
        return False
    if signature.get("key_id") != issuer.get("key_id"):
        return False
    try:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(issuer["public_key"]))
        key.verify(base64.b64decode(str(signature.get("value"))), signed_bytes(statement))
    except (InvalidSignature, ValueError, KeyError):
        return False
    return issued <= now_ms


def current(
    statements: list[dict[str, Any]],
    issuers: list[dict[str, Any]],
    principal: str,
    contract: str,
    now_ms: int,
) -> dict[str, Any]:
    """Return ``{"established", "holds", "kind"}`` for *principal* and *contract* at *now_ms*."""
    counted = {s["id"]: s for s in statements if counts(s, principal, issuers, now_ms)}
    # Rule 2: one chain. One statement supersedes nothing, every other supersedes
    # one that counts, and no two supersede the same.
    roots = [s for s in counted.values() if s["supersedes"] is None]
    followers = {s["supersedes"]: s for s in counted.values() if s["supersedes"] is not None}
    one_chain = (
        len(roots) == 1
        and len(followers) == len(counted) - 1
        and all(earlier in counted for earlier in followers)
    )
    if not one_chain:
        return {"established": False, "holds": False, "kind": ""}
    chain = [roots[0]]
    while chain[-1]["id"] in followers:
        chain.append(followers[chain[-1]["id"]])
    if len(chain) != len(counted):
        return {"established": False, "holds": False, "kind": ""}
    # Rule 3: the head decides. It holds what it lists until it expires.
    head = chain[-1]
    live = head["expires_at_ms"] is None or now_ms < head["expires_at_ms"]
    if contract in head["contracts"] and live:
        return {"established": True, "holds": True, "kind": ""}
    held_before = any(contract in s["contracts"] for s in chain)
    return {"established": True, "holds": False, "kind": "ended" if held_before else "never_held"}


def from_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Return what an ``evaluate`` request's statements establish; None if it has none."""
    signed = request.get("mandate_statements")
    if not signed:
        return None
    return current(
        signed["statements"], signed["issuers"], signed["principal"],
        request["proposal"]["contract_id"], request["premises"]["time_ms"],
    )  # fmt: skip


def run_vectors(path: str) -> int:
    """Check every query of the vectors in *path*; return how many came out wrong."""
    with open(path, encoding="utf-8") as handle:
        vectors = json.load(handle)
    wrong = total = 0
    for case in vectors["cases"]:
        for query in case["queries"]:
            got = current(
                case["statements"], vectors["issuers"], case["principal"],
                query["contract"], query["time_ms"],
            )  # fmt: skip
            total += 1
            if got != query["expect"]:
                wrong += 1
                print(f"WRONG {case['name']} at {query['time_ms']} ms: {got} != {query['expect']}")
    print(f"{total - wrong} of {total} queries right")
    return wrong


def main() -> int:
    """Run the vectors, or read one request."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("vectors", nargs="?", help="a file of test vectors")
    parser.add_argument("--request", help="a file with one evaluate request")
    args = parser.parse_args()
    if args.request:
        with open(args.request, encoding="utf-8") as handle:
            print(json.dumps(from_request(json.load(handle))))
        return 0
    if not args.vectors:
        parser.error("give a file of test vectors, or --request")
    return 1 if run_vectors(args.vectors) else 0


if __name__ == "__main__":
    sys.exit(main())
