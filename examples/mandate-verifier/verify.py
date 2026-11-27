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

SCHEMA = "agentic_datacenter.mandate/2"
SIGNED = (
    "schema", "principal", "contracts", "issuer", "issued_at_ms", "expires_at_ms",
    "supersedes", "delegation", "reason",
)  # fmt: skip
MAX_DEPTH = 8  # links of delegation followed before authority is not established


def signed_bytes(statement: dict[str, Any]) -> bytes:
    """Return what is signed and addressed: the body as canonical JSON.

    Keys sorted, no whitespace, UTF-8, no escaping of non-ASCII characters. The
    body holds only strings, integers, booleans, null and lists of strings.
    """
    body = {name: statement.get(name) for name in SIGNED}
    return json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode()


def counts(
    statement: dict[str, Any],
    issuers: list[dict[str, Any]],
    now_ms: int,
    first_seen: dict[str, int] | None = None,
) -> bool:
    """Rule 1: whether *statement* counts. One that does not is ignored.

    *first_seen* is when the site first saw each statement, by ``id``. The site
    keeps it, not the issuer, so a statement cannot be dated back past it.
    """
    if statement.get("schema") != SCHEMA:
        return False
    contracts, issued = statement.get("contracts"), statement.get("issued_at_ms")
    expires = statement.get("expires_at_ms")
    if not isinstance(contracts, list) or not all(isinstance(c, str) for c in contracts):
        return False
    if type(issued) is not int or (expires is not None and type(expires) is not int):
        return False
    if type(statement.get("delegation")) is not bool:
        return False
    if type(statement.get("issuer")) is not str or type(statement.get("reason")) is not str:
        return False
    if statement.get("supersedes") is not None and type(statement["supersedes"]) is not str:
        return False
    try:
        addressed = "sha256:" + hashlib.sha256(signed_bytes(statement)).hexdigest()
    except (TypeError, ValueError):
        return False  # a body that cannot be written as canonical JSON
    if statement.get("id") != addressed:
        return False
    signature = statement.get("signature")
    if not isinstance(signature, dict) or signature.get("alg") != "Ed25519":
        return False
    # The key it names must be one of this issuer's.
    key = next(
        (
            i
            for i in issuers
            if i.get("name") == statement.get("issuer")
            and i.get("key_id") == signature.get("key_id")
        ),
        None,
    )
    if key is None:
        return False
    try:
        public = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(key["public_key"], validate=True)
        )
        value = base64.b64decode(str(signature.get("value")), validate=True)
        public.verify(value, signed_bytes(statement))
    except (InvalidSignature, ValueError, KeyError):
        return False
    # A key signs only while it is valid: from valid_from_ms, until valid_until_ms.
    if type(key.get("valid_from_ms")) is not int or issued < key["valid_from_ms"]:
        return False
    if key.get("valid_until_ms") is not None and issued >= key.get("valid_until_ms"):
        return False
    # The same key must still have been valid when the site first saw the statement.
    if first_seen is not None:
        seen = first_seen.get(statement["id"])
        if seen is None or seen < issued or seen > now_ms:
            return False
        if key.get("valid_until_ms") is not None and seen >= key.get("valid_until_ms"):
            return False
    # Only an issuer the site trusts gives a mandate of its own. Anyone else
    # can only pass on what they hold, and must say so.
    if not statement["delegation"] and key.get("root") is not True:
        return False
    return issued <= now_ms


def chain_of(
    statements: list[dict[str, Any]],
    issuers: list[dict[str, Any]],
    principal: str,
    now_ms: int,
    first_seen: dict[str, int] | None = None,
) -> list[dict[str, Any]] | None:
    """Rule 2: the statements that count for *principal*, oldest first; None if not one chain."""
    counted = {
        s["id"]: s
        for s in statements
        if s.get("principal") == principal and counts(s, issuers, now_ms, first_seen)
    }
    roots = [s for s in counted.values() if s.get("supersedes") is None]
    followers = {s["supersedes"]: s for s in counted.values() if s.get("supersedes") is not None}
    one_chain = (
        len(roots) == 1
        and len(followers) == len(counted) - 1
        and all(earlier in counted for earlier in followers)
    )
    if not one_chain:
        return None
    chain = [roots[0]]
    while chain[-1]["id"] in followers:
        chain.append(followers[chain[-1]["id"]])
    return chain if len(chain) == len(counted) else None


def current(
    statements: list[dict[str, Any]],
    issuers: list[dict[str, Any]],
    principal: str,
    contract: str,
    now_ms: int,
    first_seen: dict[str, int] | None = None,
    depth: int = MAX_DEPTH,
) -> dict[str, Any]:
    """Return ``{"established", "holds", "kind"}`` for *principal* and *contract* at *now_ms*."""
    nothing = {"established": False, "holds": False, "kind": ""}
    chain = chain_of(statements, issuers, principal, now_ms, first_seen)
    if chain is None or depth == 0:
        return nothing
    # Rule 3: the head decides. It holds what it lists until it expires, and a
    # delegation only while whoever passed it on holds the contract too.
    head = chain[-1]
    live = head.get("expires_at_ms") is None or now_ms < head["expires_at_ms"]
    holds = contract in head["contracts"] and live
    if holds and head["delegation"]:
        giver = current(
            statements, issuers, head["issuer"], contract, now_ms, first_seen, depth - 1
        )
        if not giver["established"]:
            return nothing
        holds = giver["holds"]
    if holds:
        return {"established": True, "holds": True, "kind": ""}
    before = ever_held(statements, issuers, principal, contract, now_ms, first_seen, depth)
    return {"established": True, "holds": False, "kind": "ended" if before else "never_held"}


def ever_held(
    statements: list[dict[str, Any]],
    issuers: list[dict[str, Any]],
    principal: str,
    contract: str,
    now_ms: int,
    first_seen: dict[str, int] | None,
    depth: int,
) -> bool:
    """Whether a statement that counts ever gave *principal* the contract.

    A delegation gave it only if whoever passed it on was ever given it.
    """
    if depth == 0:
        return False
    for s in statements:
        if s.get("principal") != principal or not counts(s, issuers, now_ms, first_seen):
            continue
        if contract not in s["contracts"]:
            continue
        if not s["delegation"]:
            return True
        if ever_held(statements, issuers, s["issuer"], contract, now_ms, first_seen, depth - 1):
            return True
    return False


def from_request(request: dict[str, Any]) -> dict[str, Any] | None:
    """Return what an ``evaluate`` request's statements establish; None if it has none."""
    signed = request.get("mandate_statements")
    if not signed:
        return None
    return current(
        signed["statements"], signed["issuers"], signed["principal"],
        request["proposal"]["contract_id"], request["premises"]["time_ms"],
        signed.get("first_seen_ms"),
    )  # fmt: skip


def run_vectors(path: str) -> int:
    """Check every query of the vectors in *path*; return how many came out wrong."""
    with open(path, encoding="utf-8") as handle:
        vectors = json.load(handle)
    wrong = total = 0
    for case in vectors["cases"]:
        for query in case["queries"]:
            got = current(
                case["statements"], case["issuers"], case["principal"],
                query["contract"], query["time_ms"], case.get("first_seen_ms"),
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
