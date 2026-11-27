"""Signed sensor readings and signed receipts (ADR 0041).

Two things a party outside the simulator can verify without taking anyone's
word for it:

- **A reading.** Each row of the plant context a gate asks for is signed by
  the source it came from, the plant module that owns the point. What is
  signed is carried in the row as text (``reading``), so a verifier checks
  the signature over those bytes and never has to write a number the way
  the signer did. A reading whose signature does not verify under its
  source's key did not come from that source.
- **A receipt.** A governance system may sign each receipt it gives. The
  signature is over the receipt without its ``signature``, as canonical JSON:
  keys sorted, no whitespace, UTF-8. Keep a receipt to text, whole numbers,
  true, false and null. A number that is not whole is written here the way
  Python writes it, and a signer in another language may write it otherwise.

The source keys are test keys, derived from the source's name. They are public
by construction and never credentials. A receipt key is the governance
system's own; only its public half is given here.
"""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey
from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

from agentic_datacenter.core.state import JsonValue
from agentic_datacenter.governance.interop import canonical_json

#: The fields of a reading that are signed, in the order they are written.
READING = ("tag", "value", "unit", "quality", "time_ms")
#: Who signs a spoofed reading: not the source it names.
INTRUDER = "unlisted-device"
#: What is found of a signature: it verifies, it does not, there is none, or no
#: key was given to check it with.
VERIFIED, FAILED, NOT_SIGNED, NOT_CHECKED = "verified", "failed", "not_signed", "not_checked"


def source_of(tag: str) -> str:
    """Return the source of a point: the plant module instance that owns it."""
    return tag.rsplit(".", 1)[0]


def source_key(name: str) -> Ed25519PrivateKey:
    """Return the test key of source *name*. The same for the same name, everywhere."""
    seed = hashlib.sha256(b"agentic-datacenter sensor test key/1\x00" + name.encode()).digest()
    return Ed25519PrivateKey.from_private_bytes(seed)


def public_bytes(key: Ed25519PrivateKey) -> bytes:
    """Return the raw 32-byte public half of *key*."""
    return key.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)


def key_id(public_key: bytes) -> str:
    """Return the identifier of a raw Ed25519 public key."""
    return "sha256:" + hashlib.sha256(public_key).hexdigest()


def source_record(name: str) -> dict[str, JsonValue]:
    """Return what a gate is told of a source: its name and public key."""
    public = public_bytes(source_key(name))
    return {
        "name": name,
        "alg": "Ed25519",
        "key_id": key_id(public),
        "public_key": base64.b64encode(public).decode("ascii"),
    }


def signed_reading(row: Mapping[str, JsonValue], signer: str | None = None) -> dict[str, JsonValue]:
    """Return *row* with its source, the text that was signed and the signature.

    *signer* replaces the key and leaves the source's name, for a reading that
    did not come from where it says.
    """
    source = source_of(str(row["tag"]))
    text = json.dumps({name: row[name] for name in READING}, separators=(",", ":"))
    key = source_key(signer or source)
    return {
        **row,
        "source": source,
        "reading": text,
        "signature": {
            "alg": "Ed25519",
            "key_id": key_id(public_bytes(source_key(source))),
            "value": base64.b64encode(key.sign(text.encode("utf-8"))).decode("ascii"),
        },
    }


def reading_not_verified(row: Mapping[str, Any], sources: Sequence[Mapping[str, Any]]) -> str:
    """Return why a reading does not verify; empty if it does.

    The signature must verify over the bytes of ``reading`` under the key of
    the row's ``source``, and ``reading`` must say what the row says.
    """
    signature, text = row.get("signature"), row.get("reading")
    if not isinstance(signature, Mapping) or not isinstance(text, str):
        return "not signed"
    source = next((s for s in sources if s.get("name") == row.get("source")), None)
    if source is None:
        return "source is not known"
    if signature.get("key_id") != source.get("key_id"):
        return "signed with a key that is not the source's"
    try:
        key = Ed25519PublicKey.from_public_bytes(
            base64.b64decode(str(source["public_key"]), validate=True)
        )
        key.verify(base64.b64decode(str(signature.get("value")), validate=True), text.encode())
    except (InvalidSignature, ValueError):
        return "signature does not verify"
    try:
        said = json.loads(text)
    except ValueError:
        return "reading is not JSON"
    if not isinstance(said, dict) or any(said.get(name) != row.get(name) for name in READING):
        return "the row is not what was signed"
    return ""


# -- receipts --------------------------------------------------------------------------


def receipt_bytes(receipt: Mapping[str, Any]) -> bytes:
    """Return what a receipt's signature covers: the receipt without it, as canonical JSON."""
    return canonical_json({k: v for k, v in receipt.items() if k != "signature"})


def sign_receipt(receipt: Mapping[str, Any], key: Ed25519PrivateKey) -> dict[str, Any]:
    """Return *receipt* with an Ed25519 signature over :func:`receipt_bytes`."""
    plain = {k: v for k, v in receipt.items() if k != "signature"}
    return {
        **plain,
        "signature": {
            "alg": "Ed25519",
            "key_id": key_id(public_bytes(key)),
            "value": base64.b64encode(key.sign(receipt_bytes(plain))).decode("ascii"),
        },
    }


def receipt_signature(receipt: object, public_keys: Sequence[str]) -> str:
    """Return what is found of a receipt's signature under *public_keys*.

    Each key is a raw Ed25519 public key in base64. With no keys nothing is
    checked. A receipt without a signature is ``not_signed``.
    """
    if not public_keys:
        return NOT_CHECKED
    if not isinstance(receipt, Mapping) or not isinstance(receipt.get("signature"), Mapping):
        return NOT_SIGNED
    signature = receipt["signature"]
    if signature.get("alg") != "Ed25519":
        return FAILED
    try:
        covered = receipt_bytes(receipt)
        value = base64.b64decode(str(signature.get("value")), validate=True)
    except (TypeError, ValueError):
        return FAILED
    for text in public_keys:
        try:
            raw = base64.b64decode(text, validate=True)
            if signature.get("key_id") not in (None, key_id(raw)):
                continue
            Ed25519PublicKey.from_public_bytes(raw).verify(value, covered)
        except (InvalidSignature, ValueError):
            continue
        return VERIFIED
    return FAILED
