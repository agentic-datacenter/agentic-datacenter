"""Signed mandate statements, and how current authority follows from them (ADR 0039).

The control path's register is the truth a run is judged by. Each change in it
is also issued as a signed statement, so that a gate which authenticates
credentials has something to authenticate, and one rule says how supersession,
revocation and expiry decide who may act now:

1. A statement **counts** when it names the proposer, its ``id`` is the content
   address of its body, its issuer is one the site trusts, its signature
   verifies under that issuer's key, and it was not issued in the future.
   A statement that does not count is ignored. It neither gives nor takes away.
2. The statements that count must form **one chain**: one that supersedes
   nothing, and each other superseding the one before it. The last is the
   **head**. With no chain, or more than one, authority is not established.
3. The proposer **holds** a contract when the head lists it and the head has
   not expired: ``expires_at_ms`` is null or later than now.

So a later statement replaces the earlier one whole (supersession), a statement
with no contracts ends the mandate from the instant it was issued (revocation),
and a statement stops holding at its ``expires_at_ms`` with no further
statement (expiry).

The keys are test keys, derived from the issuer's name. They are public by
construction and never credentials.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.governance.interop import canonical_json

SCHEMA = "agentic_datacenter.mandate/1"
#: The signed fields of a statement, which are also what its ``id`` addresses.
BODY = (
    "schema", "principal", "contracts", "issuer", "issued_at_ms", "expires_at_ms",
    "supersedes", "reason",
)  # fmt: skip
#: The issuer named on a change whose maker the register was not told.
REGISTER = "mandate-register"
#: Ways a scenario presents a statement that must not count (``forged``).
FORGERIES = ("unknown_issuer", "wrong_key", "altered")
#: Who signs a forgery of the kind ``unknown_issuer``: nobody the site trusts.
OUTSIDER = "contractor-7"

Statement = Mapping[str, JsonValue]


def issuer_key(name: str) -> Ed25519PrivateKey:
    """Return the test key of issuer *name*. The same for the same name, everywhere."""
    seed = hashlib.sha256(b"agentic-datacenter mandate test key/1\x00" + name.encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def _public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def key_id(public_key: bytes) -> str:
    """Return the identifier of a raw Ed25519 public key."""
    return "sha256:" + hashlib.sha256(public_key).hexdigest()


def issuer_record(name: str) -> dict[str, JsonValue]:
    """Return what a gate is told of a trusted issuer: its name and public key."""
    public = _public(issuer_key(name))
    return {
        "name": name,
        "alg": "Ed25519",
        "key_id": key_id(public),
        "public_key": base64.b64encode(public).decode("ascii"),
    }


def statement_id(statement: Statement) -> str:
    """Return the content address of *statement*: SHA-256 over its body in canonical JSON."""
    return "sha256:" + hashlib.sha256(_signed_bytes(statement)).hexdigest()


def _signed_bytes(statement: Statement) -> bytes:
    return canonical_json({name: statement.get(name) for name in BODY})


def sign(
    principal: str,
    contracts: Sequence[str],
    issuer: str,
    issued_at_ms: int,
    expires_at_ms: int | None = None,
    supersedes: str | None = None,
    reason: str = "",
    key: Ed25519PrivateKey | None = None,
) -> dict[str, JsonValue]:
    """Return a signed statement. *key* replaces the issuer's own, for a forgery."""
    body: dict[str, JsonValue] = {
        "schema": SCHEMA,
        "principal": principal,
        "contracts": sorted(contracts),
        "issuer": issuer,
        "issued_at_ms": issued_at_ms,
        "expires_at_ms": expires_at_ms,
        "supersedes": supersedes,
        "reason": reason,
    }
    signing = key or issuer_key(issuer)
    return {
        **body,
        "id": statement_id(body),
        "signature": {
            "alg": "Ed25519",
            # Named for the issuer, also when another key signed: that is the forgery.
            "key_id": key_id(_public(issuer_key(issuer))),
            "value": base64.b64encode(signing.sign(_signed_bytes(body))).decode("ascii"),
        },
    }


def issue(principal: str, changes: Sequence[Any]) -> tuple[dict[str, JsonValue], ...]:
    """Return the register's *changes* to *principal*'s mandate as a chain of statements.

    Each change is a ``MandateChange``. Signing is deterministic, so the same
    changes give the same statements, byte for byte.
    """
    chain: list[dict[str, JsonValue]] = []
    for change in changes:
        chain.append(
            sign(
                principal,
                change.contracts,
                change.by or REGISTER,
                change.time_ms,
                change.expires_at_ms,
                str(chain[-1]["id"]) if chain else None,
                change.reason,
            )
        )
    return tuple(chain)


def forged(
    kind: str,
    principal: str,
    chain: Sequence[Statement],
    contracts: Sequence[str],
    now_ms: int,
) -> dict[str, JsonValue]:
    """Return a statement that must not count, made to look as if it followed *chain*.

    - ``unknown_issuer``: well formed and well signed, by someone the site does
      not trust.
    - ``wrong_key``: names the issuer of the chain's first statement, signed
      with another key.
    - ``altered``: the chain's first statement with other contracts and no
      expiry, a matching ``id``, and the signature of the original.

    Raises:
        ValueError: If *kind* is not one of ``FORGERIES``, or *chain* is empty.
    """
    if kind not in FORGERIES or not chain:
        raise ValueError(f"cannot forge {kind!r} on a chain of {len(chain)}")
    head, first = str(chain[-1]["id"]), chain[0]
    why = "presented by the agent"
    if kind == "unknown_issuer":
        return sign(principal, contracts, OUTSIDER, now_ms, None, head, why)
    if kind == "wrong_key":
        trusted = str(first["issuer"])
        return sign(principal, contracts, trusted, now_ms, None, head, why, issuer_key(OUTSIDER))
    changed: dict[str, JsonValue] = {
        **first, "contracts": sorted(contracts), "expires_at_ms": None, "supersedes": head,
        "issued_at_ms": now_ms,
    }  # fmt: skip
    changed["id"] = statement_id(changed)
    return changed


def not_counted(
    statement: Statement, principal: str, issuers: Sequence[Mapping[str, JsonValue]], now_ms: int
) -> str:
    """Return why *statement* does not count; empty if it does (rule 1)."""
    if statement.get("schema") != SCHEMA:
        return "unknown schema"
    if statement.get("principal") != principal:
        return "names another principal"
    contracts, issued = statement.get("contracts"), statement.get("issued_at_ms")
    expires = statement.get("expires_at_ms")
    if not isinstance(contracts, list) or not all(isinstance(c, str) for c in contracts):
        return "contracts is not a list of names"
    if not isinstance(issued, int) or isinstance(issued, bool):
        return "issued_at_ms is not an integer"
    if expires is not None and (not isinstance(expires, int) or isinstance(expires, bool)):
        return "expires_at_ms is neither null nor an integer"
    if statement.get("id") != statement_id(statement):
        return "id is not the content address of the body"
    signature = statement.get("signature")
    if not isinstance(signature, Mapping) or signature.get("alg") != "Ed25519":
        return "no Ed25519 signature"
    trusted = next((i for i in issuers if i.get("name") == statement.get("issuer")), None)
    if trusted is None:
        return "issuer is not trusted"
    if signature.get("key_id") != trusted.get("key_id"):
        return "signed with a key that is not the issuer's"
    try:
        public = Ed25519PublicKey.from_public_bytes(base64.b64decode(str(trusted["public_key"])))
        public.verify(base64.b64decode(str(signature.get("value"))), _signed_bytes(statement))
    except (InvalidSignature, ValueError):
        return "signature does not verify"
    if issued > now_ms:
        return "issued in the future"
    return ""


@dataclass(frozen=True)
class Finding:
    """What a set of statements establishes about one principal and one contract.

    Attributes:
        established: The statements that count form one chain (rule 2).
        holds: The head lists the contract and has not expired (rule 3).
        kind: Without a mandate: ``ended`` when a statement of the chain listed
            the contract, ``never_held`` when none did. Empty when it holds or
            nothing is established.
        head: The ``id`` of the head; empty when nothing is established.
        ignored: Each statement that did not count, as ``(id, why)``.
    """

    established: bool
    holds: bool
    kind: str = ""
    head: str = ""
    ignored: tuple[tuple[str, str], ...] = ()


def current(
    statements: Sequence[Statement],
    issuers: Sequence[Mapping[str, JsonValue]],
    principal: str,
    contract_id: str,
    now_ms: int,
) -> Finding:
    """Return whether *principal* holds a mandate for *contract_id* at *now_ms*."""
    counted: dict[str, Statement] = {}
    ignored: list[tuple[str, str]] = []
    for statement in statements:
        why = not_counted(statement, principal, issuers, now_ms)
        if why:
            ignored.append((str(statement.get("id", "")), why))
        else:
            counted[str(statement["id"])] = statement
    chain = _chain(counted)
    if chain is None:
        return Finding(False, False, ignored=tuple(ignored))
    head = chain[-1]
    listed = head["contracts"]
    expires = head["expires_at_ms"]
    assert isinstance(listed, list)
    live = expires is None or (isinstance(expires, int) and now_ms < expires)
    if contract_id in listed and live:
        return Finding(True, True, head=str(head["id"]), ignored=tuple(ignored))
    before = any(contract_id in s["contracts"] for s in chain)  # type: ignore[operator]
    kind = "ended" if before else "never_held"
    return Finding(True, False, kind, str(head["id"]), tuple(ignored))


def _chain(counted: Mapping[str, Statement]) -> list[Statement] | None:
    """Return the statements that count in order, oldest first; None if they are not one chain."""
    roots = [s for s in counted.values() if s.get("supersedes") is None]
    if len(roots) != 1:
        return None
    after: dict[str, Statement] = {}
    for statement in counted.values():
        earlier = statement.get("supersedes")
        if earlier is None:
            continue
        if earlier not in counted or str(earlier) in after:
            return None  # supersedes something that does not count, or a fork
        after[str(earlier)] = statement
    chain = [roots[0]]
    while str(chain[-1]["id"]) in after:
        chain.append(after[str(chain[-1]["id"])])
    return chain if len(chain) == len(counted) else None


# -- test vectors ------------------------------------------------------------------

VECTORS_SCHEMA = "agentic_datacenter.mandate-vectors/1"


def vectors() -> dict[str, JsonValue]:
    """Return the test vectors of the rule: statements, questions, and the answer to each.

    For someone who implements the rule in a system of their own, in any
    language. The committed copy is ``docs/reference/mandate-vectors.json``.
    """
    who, air, rotate = "agent-1", "pod.set_supply_air_setpoint.v1", "chw.rotate_lead_chiller.v1"
    both = [air, rotate]
    grant = sign(who, both, "operator-1", 0, reason="operator-1 gives agent-1 its mandate")
    gid = str(grant["id"])
    narrowed = sign(who, [air], "operator-2", 1000, None, gid, "operator-2 narrows it")
    revoked = sign(who, [], "operator-1", 1000, None, gid, "operator-1 withdraws it")
    timed = sign(who, both, "operator-1", 0, 5000, reason="a mandate for five seconds")
    renewed = sign(who, both, "operator-1", 4000, 9000, str(timed["id"]), "renewed in time")
    other = sign("agent-2", both, "operator-1", 500, None, gid, "for another principal")
    fork = sign(who, both, "operator-2", 1500, None, gid, "a second statement on the same one")
    dangling = sign(who, both, "operator-1", 0, None, "sha256:" + "0" * 64, "follows nothing known")
    relabelled = {**grant, "contracts": [air]}
    trusted = [issuer_record("operator-1"), issuer_record("operator-2")]

    def ask(contract: str, time_ms: int, established: bool, holds: bool, kind: str = "") -> Any:
        return {
            "contract": contract, "time_ms": time_ms,
            "expect": {"established": established, "holds": holds, "kind": kind},
        }  # fmt: skip

    def case(name: str, about: str, statements: Sequence[Statement], *queries: Any) -> Any:
        return {
            "name": name, "about": about, "principal": who,
            "statements": [dict(s) for s in statements], "queries": list(queries),
        }  # fmt: skip

    def after_revocation(kind: str) -> Statement:
        return forged(kind, who, [grant, revoked], both, 2000)

    cases = [
        case(
            "one statement", "A mandate holds what it lists, and nothing else was ever held.",
            [grant],
            ask(air, 100, True, True), ask("no.such.contract.v1", 100, True, False, "never_held"),
        ),
        case(
            "supersession", "A later statement replaces the earlier one whole.",
            [grant, narrowed],
            ask(air, 2000, True, True), ask(rotate, 2000, True, False, "ended"),
            ask(rotate, 999, True, True),
        ),
        case(
            "revocation",
            "A statement with no contracts ends the mandate from the instant it was issued, "
            "and not before.",
            [grant, revoked],
            ask(air, 999, True, True), ask(air, 1000, True, False, "ended"),
            ask(air, 2000, True, False, "ended"),
        ),
        case(
            "expiry",
            "A statement stops holding at expires_at_ms, with no further statement. "
            "The instant itself is outside.",
            [timed],
            ask(air, 4999, True, True), ask(air, 5000, True, False, "ended"),
            ask(air, 60000, True, False, "ended"),
        ),
        case(
            "renewal", "Renewed before it expired: the first expiry no longer applies.",
            [timed, renewed],
            ask(air, 6000, True, True), ask(air, 9000, True, False, "ended"),
        ),
        case(
            "forged: unknown issuer",
            "Well formed and well signed by someone the site does not trust. Ignored; "
            "the withdrawal stands.",
            [grant, revoked, after_revocation("unknown_issuer")],
            ask(air, 3000, True, False, "ended"),
        ),
        case(
            "forged: wrong key",
            "In a trusted issuer's name, signed with another key. Ignored.",
            [grant, revoked, after_revocation("wrong_key")],
            ask(air, 3000, True, False, "ended"),
        ),
        case(
            "forged: altered",
            "A real statement changed after it was signed, with a matching id. Ignored.",
            [grant, revoked, after_revocation("altered")],
            ask(air, 3000, True, False, "ended"),
        ),
        case(
            "forged: id does not match",
            "The body was changed and the id was not. The only statement does not count, "
            "so nothing is established.",
            [relabelled],
            ask(air, 100, False, False),
        ),
        case(
            "forged withdrawal",
            "A withdrawal by someone the site does not trust takes nothing away.",
            [grant, forged("unknown_issuer", who, [grant], [], 1000)],
            ask(air, 3000, True, True),
        ),
        case(
            "another principal", "A statement for someone else is ignored.",
            [grant, other],
            ask(air, 3000, True, True),
        ),
        case(
            "fork",
            "Two statements that count supersede the same one. Authority is not established: "
            "refuse.",
            [grant, narrowed, fork],
            ask(air, 3000, False, False), ask(air, 1200, True, True),
        ),
        case(
            "broken chain",
            "A statement that counts supersedes one that is not there. Not established.",
            [dangling],
            ask(air, 100, False, False),
        ),
        case(
            "nothing counts", "Only a forgery was presented. Not established.",
            [forged("unknown_issuer", who, [grant], both, 0)],
            ask(air, 100, False, False),
        ),
    ]  # fmt: skip
    return {
        "schema": VECTORS_SCHEMA,
        "generated_by": "tools/gen_reference.py, from agentic_datacenter.governance.mandates",
        "note": "Test keys, derived from the issuer's name. Never credentials.",
        "issuers": trusted,
        "cases": cases,
    }
