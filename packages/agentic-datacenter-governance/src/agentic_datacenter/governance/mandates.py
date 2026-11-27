"""Signed mandate statements, and how current authority follows from them (ADR 0039, 0040).

The control path's register is the truth a run is judged by. Each change in it
is also issued as a signed statement, so that a gate which authenticates
credentials has something to authenticate, and one rule says how supersession,
revocation, expiry, delegation, an issuer's standing and a rotated key decide
who may act now:

1. A statement **counts** when its ``id`` is the content address of its body,
   its issuer is known to the site, it is signed with a key of that issuer
   that was valid when it was issued and when the site first saw it, the
   signature verifies, it was not issued in the future, and it is either a
   delegation or comes from an issuer the site trusts to give mandates. A
   statement that does not count is ignored. It neither gives nor takes away.
2. The statements that count for one principal must form **one chain**: one
   that supersedes nothing, and each other superseding the one before it. The
   last is the **head**. With no chain, or more than one, authority is not
   established.
3. The principal **holds** a contract when the head lists it, the head has
   not expired (``expires_at_ms`` is null or later than now), and, if the
   head is a delegation, its issuer holds the contract now by this same rule.

So a later statement replaces the earlier one whole (supersession), a statement
with no contracts ends the mandate from the instant it was issued (revocation),
a statement stops holding at its ``expires_at_ms`` with no further statement
(expiry), nobody passes on more than they hold or for longer than they hold it
(delegation), and a key signs only while it is valid (standing and rotation).

The keys are test keys, derived from the issuer's name. They are public by
construction and never credentials.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.governance.interop import canonical_json

SCHEMA = "agentic_datacenter.mandate/2"
#: The signed fields of a statement, which are also what its ``id`` addresses.
BODY = (
    "schema", "principal", "contracts", "issuer", "issued_at_ms", "expires_at_ms",
    "supersedes", "delegation", "reason",
)  # fmt: skip
#: The issuer named on a change whose maker the register was not told.
REGISTER = "mandate-register"
#: Ways a scenario presents a statement that must not count (``forged``).
FORGERIES = (
    "unknown_issuer", "wrong_key", "altered", "retired_key", "former_issuer", "backdated",
)  # fmt: skip
#: Who signs a forgery of the kind ``unknown_issuer``: nobody the site knows.
OUTSIDER = "contractor-7"
#: How many links of delegation are followed before authority is not established.
MAX_DEPTH = 8
#: How a site reads a delegation (ADR 0048). ``holdings``: it holds while whoever passed
#: it on holds the contract now. ``grant_bound``: it holds only under the very grant its
#: issuer held when it was passed on, and only if it lists no more than that grant did.
HOLDINGS, GRANT_BOUND = "holdings", "grant_bound"
MODELS = (HOLDINGS, GRANT_BOUND)

Statement = Mapping[str, JsonValue]
Issuer = Mapping[str, JsonValue]


def issuer_key(name: str, generation: int = 0) -> Ed25519PrivateKey:
    """Return a test key of issuer *name*. The same for the same name, everywhere.

    *generation* counts the issuer's keys: 0 is its first, and each rotation
    takes the next.
    """
    label = name if generation == 0 else f"{name}\x00{generation}"
    seed = hashlib.sha256(b"agentic-datacenter mandate test key/1\x00" + label.encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def _public(key: Ed25519PrivateKey) -> bytes:
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def key_id(public_key: bytes) -> str:
    """Return the identifier of a raw Ed25519 public key."""
    return "sha256:" + hashlib.sha256(public_key).hexdigest()


def issuer_record(
    name: str,
    root: bool = True,
    generation: int = 0,
    valid_from_ms: int = 0,
    valid_until_ms: int | None = None,
) -> dict[str, JsonValue]:
    """Return what a gate is told of one key of an issuer the site knows.

    ``root`` is whether the site trusts the issuer to give a mandate of its
    own; one that is not root can only pass on what it holds. The key is valid
    from ``valid_from_ms`` until ``valid_until_ms``, the latter excluded; null
    for a key still in use.
    """
    public = _public(issuer_key(name, generation))
    return {
        "name": name,
        "root": root,
        "alg": "Ed25519",
        "key_id": key_id(public),
        "public_key": base64.b64encode(public).decode("ascii"),
        "valid_from_ms": valid_from_ms,
        "valid_until_ms": valid_until_ms,
    }


def issuer_records(
    name: str, root: bool, events: Sequence[tuple[str, int]] = ()
) -> list[dict[str, JsonValue]]:
    """Return every key of issuer *name*, from what happened to it, oldest first.

    Each of *events* is ``("rotated", time_ms)``, which retires the key in use
    and starts the next, or ``("ended", time_ms)``, which retires it and
    starts none: the issuer's standing has ended.
    """
    records, start, generation, standing = [], 0, 0, True
    for kind, at_ms in events:
        if not standing:
            break
        records.append(issuer_record(name, root, generation, start, at_ms))
        start, generation, standing = at_ms, generation + 1, kind == "rotated"
    if standing:
        records.append(issuer_record(name, root, generation, start, None))
    return records


def generation_at(events: Sequence[tuple[str, int]], time_ms: int) -> int | None:
    """Return which key an issuer signs with at *time_ms*; None if its standing has ended."""
    generation = 0
    for kind, at_ms in events:
        if at_ms > time_ms:
            break
        if kind == "ended":
            return None
        generation += 1
    return generation


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
    delegation: bool = False,
    generation: int = 0,
) -> dict[str, JsonValue]:
    """Return a signed statement.

    It is signed with the issuer's key of *generation* and names that key.
    *key* replaces the signing key and leaves the name, for a forgery.
    """
    body: dict[str, JsonValue] = {
        "schema": SCHEMA,
        "principal": principal,
        "contracts": sorted(contracts),
        "issuer": issuer,
        "issued_at_ms": issued_at_ms,
        "expires_at_ms": expires_at_ms,
        "supersedes": supersedes,
        "delegation": delegation,
        "reason": reason,
    }
    named = issuer_key(issuer, generation)
    return {
        **body,
        "id": statement_id(body),
        "signature": {
            "alg": "Ed25519",
            "key_id": key_id(_public(named)),
            "value": base64.b64encode((key or named).sign(_signed_bytes(body))).decode("ascii"),
        },
    }


def issue(
    principal: str,
    changes: Sequence[Any],
    generation: Callable[[str, int], int] = lambda name, time_ms: 0,
) -> tuple[dict[str, JsonValue], ...]:
    """Return the register's *changes* to *principal*'s mandate as a chain of statements.

    Each change is a ``MandateChange``. *generation* says which of an issuer's
    keys was in use at an instant. Signing is deterministic, so the same
    changes give the same statements, byte for byte.
    """
    chain: list[dict[str, JsonValue]] = []
    for change in changes:
        issuer = change.by or REGISTER
        chain.append(
            sign(
                principal,
                change.contracts,
                issuer,
                change.time_ms,
                change.expires_at_ms,
                str(chain[-1]["id"]) if chain else None,
                change.reason,
                delegation=bool(change.delegated),
                generation=generation(issuer, change.time_ms),
            )
        )
    return tuple(chain)


def forged(
    kind: str,
    principal: str,
    chain: Sequence[Statement],
    contracts: Sequence[str],
    now_ms: int,
    issuers: Sequence[Issuer] = (),
) -> dict[str, JsonValue]:
    """Return a statement that must not count, made to look as if it followed *chain*.

    *chain* is the principal's own statements, oldest first.

    - ``unknown_issuer``: well formed and well signed, by someone the site does
      not know.
    - ``wrong_key``: names the issuer of the chain's first statement, signed
      with another key.
    - ``altered``: the chain's first statement with other contracts and no
      expiry, a matching ``id``, and the signature of the original.
    - ``retired_key``: well signed now with a key its issuer has rotated out.
    - ``former_issuer``: well signed now, with its own key, by an issuer whose
      standing has ended.
    - ``backdated``: well signed with a key its issuer has rotated out, and
      dated one millisecond before the key was retired. Only when the site
      first saw it tells it from a statement that counts.

    Raises:
        ValueError: If *kind* is not one of ``FORGERIES``, *chain* is empty, or
            *issuers* has no retired key or former issuer to forge with.
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
    if kind == "altered":
        changed: dict[str, JsonValue] = {
            **first, "contracts": sorted(contracts), "expires_at_ms": None, "supersedes": head,
            "issued_at_ms": now_ms,
        }  # fmt: skip
        changed["id"] = statement_id(changed)
        return changed
    in_use = {str(i["name"]) for i in issuers if i.get("valid_until_ms") is None}
    for record in issuers:
        if not record.get("root") or record.get("valid_until_ms") is None:
            continue
        name = str(record["name"])
        if (kind != "former_issuer") != (name in in_use):
            continue
        generation = _generation_of(name, str(record["key_id"]))
        retired = int(str(record["valid_until_ms"]))
        dated = retired - 1 if kind == "backdated" else now_ms
        return sign(principal, contracts, name, dated, None, head, why, generation=generation)
    raise ValueError(f"cannot forge {kind!r}: no such key among the issuers")


def _generation_of(name: str, wanted: str) -> int:
    for generation in range(64):
        if key_id(_public(issuer_key(name, generation))) == wanted:
            return generation
    raise ValueError(f"{wanted} is not a key of {name}")


def not_counted(
    statement: Statement,
    principal: str,
    issuers: Sequence[Issuer],
    now_ms: int,
    first_seen: Mapping[str, int] | None = None,
) -> str:
    """Return why *statement* does not count for *principal*; empty if it does (rule 1).

    *first_seen* says, by ``id``, when the site first saw each statement. It
    is kept by the site and not by the issuer, so it cannot be dated back.
    Without it, only the time a statement says it was issued is checked.
    """
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
    if not isinstance(statement.get("delegation"), bool):
        return "delegation is not true or false"
    if not isinstance(statement.get("issuer"), str) or not isinstance(statement.get("reason"), str):
        return "issuer or reason is not text"
    earlier = statement.get("supersedes")
    if earlier is not None and not isinstance(earlier, str):
        return "supersedes is neither null nor an id"
    try:
        addressed = statement_id(statement)
    except (TypeError, ValueError):
        return "the body cannot be written as canonical JSON"
    if statement.get("id") != addressed:
        return "id is not the content address of the body"
    signature = statement.get("signature")
    if not isinstance(signature, Mapping) or signature.get("alg") != "Ed25519":
        return "no Ed25519 signature"
    known = [i for i in issuers if i.get("name") == statement.get("issuer")]
    if not known:
        return "issuer is not known"
    record = next((i for i in known if i.get("key_id") == signature.get("key_id")), None)
    if record is None:
        return "signed with a key that is not the issuer's"
    try:
        public = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(str(record["public_key"]), validate=True)
        )
        value = base64.b64decode(str(signature.get("value")), validate=True)
        public.verify(value, _signed_bytes(statement))
    except (InvalidSignature, ValueError):
        return "signature does not verify"
    start, end = record.get("valid_from_ms", 0), record.get("valid_until_ms")
    if not isinstance(start, int) or issued < start:
        return "issued before the key was valid"
    if end is not None and (not isinstance(end, int) or issued >= end):
        return "issued after the key was retired"
    if first_seen is not None:
        seen = first_seen.get(str(statement["id"]))
        if seen is None:
            return "the site has not seen it"
        if seen < issued:
            return "seen before it says it was issued"
        if end is not None and seen >= end:
            return "first seen after the key was retired"
        if seen > now_ms:
            return "first seen in the future"
    if not statement["delegation"] and record.get("root") is not True:
        return "issuer may only pass on what it holds"
    if issued > now_ms:
        return "issued in the future"
    return ""


@dataclass(frozen=True)
class Finding:
    """What a set of statements establishes about one principal and one contract.

    Attributes:
        established: The statements that count form one chain, for the
            principal and for everyone its mandate is passed on from (rule 2).
        holds: The head lists the contract, has not expired, and whoever passed
            it on holds it too (rule 3).
        kind: Without a mandate: ``ended`` when the contract was once held,
            ``never_held`` when it was not, and ``unbound`` when, at a site that
            binds a delegation to its grant, the head is a delegation that is
            not under the grant its issuer holds now. Empty when it holds or
            nothing is established.
        head: The ``id`` of the principal's head; empty when nothing is established.
        ignored: Each statement of the principal's that did not count, as ``(id, why)``.
    """

    established: bool
    holds: bool
    kind: str = ""
    head: str = ""
    ignored: tuple[tuple[str, str], ...] = ()


def current(
    statements: Sequence[Statement],
    issuers: Sequence[Issuer],
    principal: str,
    contract_id: str,
    now_ms: int,
    first_seen: Mapping[str, int] | None = None,
    model: str = HOLDINGS,
) -> Finding:
    """Return whether *principal* holds a mandate for *contract_id* at *now_ms*.

    *first_seen* is when the site first saw each statement, by ``id``; see
    :func:`not_counted`. *model* is how the site reads a delegation, one of
    :data:`MODELS`.

    Raises:
        ValueError: If *model* is not one of :data:`MODELS`.
    """
    if model not in MODELS:
        raise ValueError(f"an authorization model is one of {', '.join(MODELS)}, not {model!r}")
    return _current(
        statements, issuers, principal, contract_id, now_ms, MAX_DEPTH, first_seen, model
    )


def _counted_chain(
    statements: Sequence[Statement],
    issuers: Sequence[Issuer],
    principal: str,
    now_ms: int,
    first_seen: Mapping[str, int] | None,
) -> tuple[list[Statement] | None, list[tuple[str, str]]]:
    """Return the principal's statements that count, as one chain or None, and those ignored."""
    counted: dict[str, Statement] = {}
    ignored: list[tuple[str, str]] = []
    for statement in statements:
        if statement.get("principal") != principal:
            continue  # another principal's; read when a delegation leads to it
        why = not_counted(statement, principal, issuers, now_ms, first_seen)
        if why:
            ignored.append((str(statement.get("id", "")), why))
        else:
            counted[str(statement["id"])] = statement
    return _chain(counted), ignored


def _bound(
    head: Statement,
    statements: Sequence[Statement],
    issuers: Sequence[Issuer],
    now_ms: int,
    first_seen: Mapping[str, int] | None,
) -> bool | None:
    """Whether a delegation is under the grant its issuer holds now; None if nothing is established.

    The grant a delegation was passed on under is the statement that was the
    head of its issuer's chain when the delegation was issued. It is bound
    while that same statement is still the issuer's head, and only if it lists
    nothing that grant did not list.
    """
    chain, _ = _counted_chain(statements, issuers, str(head["issuer"]), now_ms, first_seen)
    if chain is None:
        return None
    issued = head["issued_at_ms"]
    assert isinstance(issued, int)
    earlier = [
        s for s in chain if isinstance(s["issued_at_ms"], int) and s["issued_at_ms"] <= issued
    ]
    if not earlier or earlier[-1] is not chain[-1]:
        return False  # passed on before any grant, or the grant has been replaced since
    listed, granted = head["contracts"], chain[-1]["contracts"]
    assert isinstance(listed, list) and isinstance(granted, list)
    return set(listed) <= set(granted)


def _current(
    statements: Sequence[Statement],
    issuers: Sequence[Issuer],
    principal: str,
    contract_id: str,
    now_ms: int,
    depth: int,
    first_seen: Mapping[str, int] | None = None,
    model: str = HOLDINGS,
) -> Finding:
    chain, ignored = _counted_chain(statements, issuers, principal, now_ms, first_seen)
    if chain is None or depth == 0:
        return Finding(False, False, ignored=tuple(ignored))
    head = chain[-1]
    listed, expires = head["contracts"], head.get("expires_at_ms")
    assert isinstance(listed, list)
    live = expires is None or (isinstance(expires, int) and now_ms < expires)
    holds = contract_id in listed and live
    unbound = False
    if holds and head["delegation"] and model == GRANT_BOUND:
        bound = _bound(head, statements, issuers, now_ms, first_seen)
        if bound is None:
            return Finding(False, False, ignored=tuple(ignored))
        holds, unbound = bound, not bound
    if holds and head["delegation"]:
        # Nobody passes on more than they hold, or for longer than they hold it.
        giver = _current(
            statements, issuers, str(head["issuer"]), contract_id, now_ms, depth - 1,
            first_seen, model,
        )  # fmt: skip
        if not giver.established:
            return Finding(False, False, ignored=tuple(ignored))
        holds = giver.holds
        unbound = giver.kind == "unbound"
    if holds:
        return Finding(True, True, head=str(head["id"]), ignored=tuple(ignored))
    before = _ever(statements, issuers, principal, contract_id, now_ms, depth, first_seen)
    kind = "unbound" if unbound else "ended" if before else "never_held"
    return Finding(True, False, kind, str(head["id"]), tuple(ignored))


def _ever(
    statements: Sequence[Statement],
    issuers: Sequence[Issuer],
    principal: str,
    contract_id: str,
    now_ms: int,
    depth: int,
    first_seen: Mapping[str, int] | None = None,
) -> bool:
    """Whether a statement that counts ever gave *principal* the contract.

    A delegation gave it only if whoever passed it on was ever given it.
    """
    if depth == 0:
        return False
    for statement in statements:
        listed = statement.get("contracts")
        if statement.get("principal") != principal or not isinstance(listed, list):
            continue
        if contract_id not in listed:
            continue
        if not_counted(statement, principal, issuers, now_ms, first_seen):
            continue
        if not statement["delegation"]:
            return True
        giver = str(statement["issuer"])
        if _ever(statements, issuers, giver, contract_id, now_ms, depth - 1, first_seen):
            return True
    return False


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

VECTORS_SCHEMA = "agentic_datacenter.mandate-vectors/2"


def vectors() -> dict[str, JsonValue]:
    """Return the test vectors of the rule: statements, questions, and the answer to each.

    For someone who implements the rule in a system of their own, in any
    language. The committed copy is ``docs/reference/mandate-vectors.json``.
    Each case has its own ``issuers``.
    """
    who, air, rotate = "agent-1", "pod.set_supply_air_setpoint.v1", "chw.rotate_lead_chiller.v1"
    lead = "orchestrator-1"
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
    worded = sign(who, [air], "operator-1", 0, reason='Skiftleder sa "kjør", ±1 °C\ttil kl. 14')
    trusted = [issuer_record("operator-1"), issuer_record("operator-2")]

    # Delegation: operator-1 gives the orchestrator its mandate, and the
    # orchestrator passes some of it on to the agent.
    to_lead = sign(lead, [air], "operator-1", 0, reason="operator-1 gives the orchestrator air")
    to_lead_timed = sign(lead, both, "operator-1", 0, 5000, reason="for five seconds")
    lead_revoked = sign(lead, [], "operator-1", 2000, None, str(to_lead["id"]), "withdrawn")
    passed_on = sign(who, both, lead, 100, reason="the orchestrator passes on more than it holds",
                     delegation=True)  # fmt: skip
    passed_long = sign(who, both, lead, 100, 60000, reason="passed on for a minute",
                       delegation=True)  # fmt: skip
    self_made = sign(who, both, lead, 100, reason="the orchestrator gives a mandate of its own")
    loop_a = sign(who, [air], lead, 0, reason="from the orchestrator", delegation=True)
    loop_b = sign(lead, [air], who, 0, reason="from the agent", delegation=True)
    with_lead = [*trusted, issuer_record(lead, root=False)]
    looped = [*with_lead, issuer_record(who, root=False)]

    # Standing and rotation: operator-1 rotates its key at 3000; operator-2 leaves at 3000.
    rotated = [*issuer_records("operator-1", True, [("rotated", 3000)]), trusted[1]]
    departed = [trusted[0], *issuer_records("operator-2", True, [("ended", 3000)])]
    old_key_late = sign(who, both, "operator-1", 4000, None, str(revoked["id"]), "old key, late")
    new_key = sign(who, [air], "operator-1", 4000, None, gid, "signed with the new key",
                   generation=1)  # fmt: skip
    new_key_early = sign(who, both, "operator-1", 2000, None, gid, "new key, dated before it",
                         generation=1)  # fmt: skip
    by_departed = sign(who, both, "operator-2", 4000, None, str(revoked["id"]), "after leaving")
    before_leaving = sign(who, [air], "operator-2", 1000, None, gid, "operator-2 narrows it")
    # Dated one millisecond before the key was retired at 3000, by whoever holds it now.
    dated_back = sign(who, both, "operator-1", 2999, None, str(revoked["id"]), "dated back")
    unsigned = {k: v for k, v in revoked.items() if k != "signature"}

    def seen(*pairs: tuple[Statement, int]) -> dict[str, int]:
        return {str(statement["id"]): at_ms for statement, at_ms in pairs}

    def ask(contract: str, time_ms: int, established: bool, holds: bool, kind: str = "") -> Any:
        return {
            "contract": contract, "time_ms": time_ms,
            "expect": {"established": established, "holds": holds, "kind": kind},
        }  # fmt: skip

    def case(
        name: str, about: str, statements: Sequence[Statement], *queries: Any,
        issuers: Sequence[Issuer] = trusted, first_seen: Mapping[str, int] | None = None,
    ) -> Any:  # fmt: skip
        return {
            "name": name, "about": about, "principal": who,
            "issuers": [dict(i) for i in issuers],
            "statements": [dict(s) for s in statements], "queries": list(queries),
            # Only in a case that is about when a statement was first seen.
            **({"first_seen_ms": dict(first_seen)} if first_seen is not None else {}),
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
            "canonical bytes",
            "A reason with characters outside ASCII, quotation marks and a tab. Characters "
            "outside ASCII are written as they are, in UTF-8; the quotation mark, the "
            "backslash and control characters are escaped. For this body that is RFC 8785.",
            [worded],
            ask(air, 100, True, True),
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
            "Well formed and well signed by someone the site does not know. Ignored; "
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
            "A withdrawal by someone the site does not know takes nothing away.",
            [grant, forged("unknown_issuer", who, [grant], [], 1000)],
            ask(air, 3000, True, True),
        ),
        case(
            "another principal", "A statement for someone else is not read for this one.",
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
        case(
            "delegation",
            "The orchestrator passes its mandate on. The agent holds what both statements "
            "list, and never what the orchestrator did not hold.",
            [to_lead, passed_on],
            ask(air, 500, True, True), ask(rotate, 500, True, False, "never_held"),
            issuers=with_lead,
        ),
        case(
            "delegation: the giver's mandate is withdrawn",
            "When the orchestrator's mandate ends, so does what it passed on, with no "
            "statement about the agent.",
            [to_lead, passed_on, lead_revoked],
            ask(air, 1999, True, True), ask(air, 2000, True, False, "ended"),
            issuers=with_lead,
        ),
        case(
            "delegation: the giver's mandate expires",
            "Passed on for a minute by someone who holds it for five seconds: five seconds.",
            [to_lead_timed, passed_long],
            ask(rotate, 4999, True, True), ask(rotate, 5000, True, False, "ended"),
            issuers=with_lead,
        ),
        case(
            "delegation: the giver has no statements",
            "Passed on by someone for whom nothing is established. Not established.",
            [passed_on],
            ask(air, 500, False, False),
            issuers=with_lead,
        ),
        case(
            "delegation: not marked as one",
            "The orchestrator signs a mandate of its own. It is not an issuer the site "
            "trusts to do that, so the statement does not count.",
            [to_lead, self_made],
            ask(air, 500, False, False),
            issuers=with_lead,
        ),
        case(
            "delegation: a loop",
            "Each passes on to the other and nobody was given anything. Not established.",
            [loop_a, loop_b],
            ask(air, 500, False, False),
            issuers=looped,
        ),
        case(
            "rotation",
            "The old key signed before it was retired and the new key after. Both count.",
            [grant, new_key],
            ask(rotate, 3500, True, True), ask(air, 4500, True, True),
            ask(rotate, 4500, True, False, "ended"),
            issuers=rotated,
        ),
        case(
            "rotation: the retired key signs afterwards",
            "Well signed with a key that had been rotated out when it was issued. Ignored.",
            [grant, revoked, old_key_late],
            ask(air, 4500, True, False, "ended"),
            issuers=rotated,
        ),
        case(
            "rotation: the new key, dated before it was valid",
            "A key signs only from the instant it is valid. Ignored.",
            [grant, new_key_early],
            ask(rotate, 4500, True, True),
            issuers=rotated,
        ),
        case(
            "standing ended: what was given before stays",
            "An issuer who has left does not take back what it gave while it had standing.",
            [grant, before_leaving],
            ask(air, 4500, True, True), ask(rotate, 4500, True, False, "ended"),
            issuers=departed,
        ),
        case(
            "standing ended: a statement issued afterwards",
            "Well signed with the issuer's own key after its standing ended. Ignored.",
            [grant, revoked, by_departed],
            ask(air, 4500, True, False, "ended"),
            issuers=departed,
        ),
        case(
            "an unsigned withdrawal",
            "A withdrawal with no signature: someone says the mandate was withdrawn. It "
            "does not count, so the mandate is held as before. A withdrawal is evidence "
            "only when it is signed.",
            [grant, unsigned],
            ask(air, 3000, True, True),
        ),
        case(
            "dated back: first seen after the key was retired",
            "Signed with a retired key and dated one millisecond before it was retired. "
            "By its own date it would count. The site first saw it at 4000, after the key "
            "was retired at 3000, so it does not.",
            [grant, revoked, dated_back],
            ask(air, 4500, True, False, "ended"),
            issuers=rotated,
            first_seen=seen((grant, 0), (revoked, 1000), (dated_back, 4000)),
        ),
        case(
            "the same statement, seen in time",
            "The same bytes, first seen at 2999 while the key was valid. It counts, and what "
            "the key signed while it was valid stays after the key is retired.",
            [grant, revoked, dated_back],
            ask(air, 4500, True, True),
            issuers=rotated,
            first_seen=seen((grant, 0), (revoked, 1000), (dated_back, 2999)),
        ),
        case(
            "a statement the site has not seen",
            "With times of first sight given, a statement that is not among them does not "
            "count, whatever it says.",
            [grant, narrowed],
            ask(rotate, 2000, True, True),
            first_seen=seen((grant, 0)),
        ),
    ]  # fmt: skip
    return {
        "schema": VECTORS_SCHEMA,
        "generated_by": "tools/gen_reference.py, from agentic_datacenter.governance.mandates",
        "note": "Test keys, derived from the issuer's name. Never credentials.",
        "cases": cases,
    }


def vectors_grant_bound() -> dict[str, JsonValue]:
    """Return test vectors for a site that binds a delegation to its grant (ADR 0048).

    Every case is given twice, once for each model, on the same statements: the
    two models differ only in what becomes of a delegation when its issuer's
    own mandate changes. The committed copy is
    ``docs/reference/mandate-vectors-grant-bound.json``. Proposed in issue 76.
    """
    who, lead, second = "agent-1", "orchestrator-1", "orchestrator-2"
    air, rotate = "pod.set_supply_air_setpoint.v1", "chw.rotate_lead_chiller.v1"
    both = [air, rotate]
    issuers = [
        issuer_record("operator-1"), issuer_record(lead, root=False),
        issuer_record(second, root=False),
    ]  # fmt: skip

    def passed(
        to: str, contracts: list[str], by: str, at_ms: int, why: str, after: Any = None
    ) -> Statement:
        earlier = None if after is None else str(after["id"])
        return sign(to, contracts, by, at_ms, None, earlier, why, delegation=True)

    grant = sign(lead, [air], "operator-1", 0, reason="operator-1 gives the orchestrator air")
    gid = str(grant["id"])
    to_agent = passed(who, [air], lead, 100, "the orchestrator passes air on to the agent")
    withdrawn = sign(lead, [], "operator-1", 2000, None, gid, "operator-1 withdraws it")
    restored = sign(
        lead, [air], "operator-1", 4000, None, str(withdrawn["id"]), "and gives it again"
    )
    again = passed(who, [air], lead, 5000, "passed on again, under the new grant", to_agent)
    wide = passed(who, both, lead, 100, "the orchestrator passes on more than it holds")
    widened = sign(lead, both, "operator-1", 2000, None, gid, "operator-1 adds rotation")
    wide_again = passed(who, both, lead, 3000, "passed on again, under the wider grant", wide)
    renewed = sign(lead, [air], "operator-1", 2000, None, gid, "the same mandate, given again")
    early = passed(who, [air], lead, 100, "passed on before the orchestrator held anything")
    late_grant = sign(lead, [air], "operator-1", 200, reason="operator-1 gives air, later")
    at_once = passed(who, [air], lead, 0, "passed on at the instant it was given")
    to_second = passed(second, [air], lead, 50, "the orchestrator passes air on to a second")
    from_second = passed(who, [air], second, 100, "the second passes it on to the agent")

    def ask(contract: str, time_ms: int, holds: bool, kind: str = "") -> Any:
        return {
            "contract": contract, "time_ms": time_ms,
            "expect": {"established": True, "holds": holds, "kind": kind},
        }  # fmt: skip

    def nothing(contract: str, time_ms: int) -> Any:
        return {
            "contract": contract, "time_ms": time_ms,
            "expect": {"established": False, "holds": False, "kind": ""},
        }  # fmt: skip

    def pair(name: str, about: str, statements: Sequence[Statement], held: Any, bound: Any) -> Any:
        return [
            {
                "name": f"{name} ({model})", "about": about, "model": model, "principal": who,
                "issuers": [dict(i) for i in issuers],
                "statements": [dict(s) for s in statements], "queries": list(queries),
            }
            for model, queries in ((HOLDINGS, held), (GRANT_BOUND, bound))
        ]  # fmt: skip

    cases = [
        *pair(
            "authority restored at the source",
            "The operator withdraws the orchestrator's mandate and later gives it the same "
            "again. The orchestrator passes nothing on anew. Where a delegation holds while "
            "its issuer holds, the agent has its mandate back. Where a delegation is bound "
            "to the grant it was passed on under, it has not: that grant is gone.",
            [grant, to_agent, withdrawn, restored],
            [ask(air, 1000, True), ask(air, 3000, False, "ended"), ask(air, 5000, True)],
            [ask(air, 1000, True), ask(air, 3000, False, "unbound"),
             ask(air, 5000, False, "unbound")],
        ),
        *pair(
            "passed on again after the restoration",
            "The same, and then the orchestrator passes the mandate on again. Under either "
            "model the agent holds it.",
            [grant, to_agent, withdrawn, restored, again],
            [ask(air, 6000, True)], [ask(air, 6000, True)],
        ),
        *pair(
            "authority widened at the source",
            "The orchestrator holds air and passes on air and rotation. Later the operator "
            "gives the orchestrator rotation too. Where a delegation holds while its issuer "
            "holds, the agent then holds rotation. Where it is bound to its grant, a "
            "delegation that listed more than its grant gives nothing, before or after.",
            [grant, wide, widened],
            [ask(air, 1000, True), ask(rotate, 1000, False, "never_held"),
             ask(rotate, 3000, True)],
            [ask(air, 1000, False, "unbound"), ask(rotate, 1000, False, "unbound"),
             ask(rotate, 3000, False, "unbound")],
        ),
        *pair(
            "passed on again after the widening",
            "The same, and then the orchestrator passes both on again under the wider grant. "
            "Under either model the agent holds both.",
            [grant, wide, widened, wide_again],
            [ask(rotate, 4000, True), ask(air, 4000, True)],
            [ask(rotate, 4000, True), ask(air, 4000, True)],
        ),
        *pair(
            "the same mandate given again",
            "The operator replaces the orchestrator's mandate with one that lists the same. "
            "Where a delegation is bound to its grant this too ends what was passed on, "
            "because the grant it was passed on under has been replaced.",
            [grant, to_agent, renewed],
            [ask(air, 3000, True)], [ask(air, 3000, False, "unbound")],
        ),
        *pair(
            "passed on before anything was held",
            "The orchestrator passes air on before it is given air. Until it is given air, "
            "nothing is established for it, and so nothing for the agent. Afterwards, where "
            "a delegation holds while its issuer holds, the agent holds air. Where it is "
            "bound to a grant, there was no grant to bind it to.",
            [early, late_grant],
            [nothing(air, 150), ask(air, 300, True)],
            [nothing(air, 150), ask(air, 300, False, "unbound")],
        ),
        *pair(
            "passed on at the instant it was given",
            "A delegation issued at the same instant as its grant is under that grant.",
            [grant, at_once],
            [ask(air, 100, True)], [ask(air, 100, True)],
        ),
        *pair(
            "two links, and the first grant is replaced",
            "The mandate goes through two orchestrators to the agent. The operator replaces "
            "the first orchestrator's mandate with one that lists the same. Where delegations "
            "are bound to their grants, the second orchestrator's is no longer under the "
            "first's grant, and so nothing below it holds either.",
            [grant, to_second, from_second, renewed],
            [ask(air, 1000, True), ask(air, 3000, True)],
            [ask(air, 1000, True), ask(air, 3000, False, "unbound")],
        ),
    ]  # fmt: skip
    return {
        "schema": VECTORS_SCHEMA,
        "generated_by": "tools/gen_reference.py, from agentic_datacenter.governance.mandates",
        "note": "Test keys, derived from the issuer's name. Never credentials. A case names "
        "the model it is read under in `model`.",
        "cases": cases,
    }
