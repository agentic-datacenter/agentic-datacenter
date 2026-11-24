"""Host evidence in shirudo's keepalive format, made and checked without a TPM (ADR 0032).

A shirudo target sends its collector a keepalive: a compact JSON body that says
which build, configuration, kernel and upatch set it runs and whether its guards
hold, and a TPM quote over the SHA-256 of that body. The format is
``shirudo.keepalive/1`` at the commit in ``SHIRUDO_PIN``.

The simulator plays the hosts between the agent and the plant as such targets.
Their keys are software P-256 keys derived from the run's seed, and every
signature is deterministic (RFC 6979), so a run stays reproducible.
:func:`check_quote` runs the seven checks of ``shirudo-quote-check`` in its order
and gives its verdicts. Its parsers take what shirudo's take and refuse what they
refuse (``tpm_public_parse``, ``tpm_attest_parse`` and
``tpm_ecdsa_signature_parse`` in ``util/tpm_wire.c``, ``quote_row_check`` in
``tools/quote-check/row.c``), down to the size of every field. A quote that
checks proves that the body is unchanged since the key signed it. It never
proves that the key lives in a TPM, here or in shirudo.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import (
    decode_dss_signature,
    encode_dss_signature,
)

SCHEMA = "shirudo.keepalive/1"

#: The 23 keys of a body, in the order the format requires.
BODY_KEYS = (
    "schema", "boot_id", "version_id", "config_root", "kernel_release", "image_id",
    "image_version", "image_root", "verdict", "cond", "flags", "tamper", "integrity",
    "tree_id", "generation", "base_seq", "last_seq", "base_root", "projection_root", "mask",
    "set_sha256", "count", "not_ok",
)  # fmt: skip
MAX_BODY_BYTES = 4095

Verdict = Literal["ok", "malformed", "bad_signature", "body_mismatch"]

_TPM_GENERATED = 0xFF544347
_TPM_ST_ATTEST_QUOTE = 0x8018
_TPM_ALG_ECC = 0x0023
_TPM_ALG_SHA256 = 0x000B
_TPM_ALG_ECDSA = 0x0018
_TPM_ALG_NULL = 0x0010
_TPM_ALG_AES = 0x0006
_TPM_ALG_CFB = 0x0043
_TPM_ECC_NIST_P256 = 0x0003
_TPM_RH_ENDORSEMENT = 0x4000000B
#: fixedTPM, fixedParent, sensitiveDataOrigin, userWithAuth, restricted, sign: the
#: attributes of the attestation key shirudo creates. A software key carries them too.
_AK_ATTRIBUTES = 0x00050072
_MAX_ATTEST, _MAX_SIG, _MAX_AK = 1024, 160, 512
_NAME_LEN = 34
_PCR_SELECT_LEN = 3
_HEX64 = re.compile(r"[0-9a-fA-F]{64}")
_P256_ORDER = 0xFFFFFFFF00000000FFFFFFFFFFFFFFFFBCE6FAADA7179E84F3B9CAC2FC632551


class KeepaliveError(ValueError):
    """A keepalive body that is not in the format."""


@dataclass(frozen=True)
class Quote:
    """The ``shirudo.quote`` attribute: three fields in standard base64 with padding."""

    attest: str
    sig: str
    ak: str

    def attribute(self) -> str:
        """Return the attribute as a keepalive record carries it."""
        return f"attest={self.attest};sig={self.sig};ak={self.ak}"


class _Reader:
    def __init__(self, data: bytes) -> None:
        self.data, self.at = data, 0

    def take(self, n: int) -> bytes:
        if self.at + n > len(self.data):
            raise ValueError("short")
        out = self.data[self.at : self.at + n]
        self.at += n
        return out

    def u8(self) -> int:
        return self.take(1)[0]

    def u16(self) -> int:
        return int(struct.unpack(">H", self.take(2))[0])

    def u32(self) -> int:
        return int(struct.unpack(">I", self.take(4))[0])

    def u64(self) -> int:
        return int(struct.unpack(">Q", self.take(8))[0])

    def sized(self) -> bytes:
        return self.take(self.u16())

    def done(self) -> None:
        if self.at != len(self.data):
            raise ValueError("trailing bytes")


def _sized(data: bytes) -> bytes:
    return struct.pack(">H", len(data)) + data


def _sized_max(r: _Reader, limit: int) -> bytes:
    """A ``TPM2B`` of at most *limit* bytes, as ``get2b`` in shirudo's ``util/tpm_wire.c``."""
    n = r.u16()
    if n > limit:
        raise ValueError(f"a sized field of {n} bytes, more than {limit}")
    return r.take(n)


def _sized_exact(r: _Reader, size: int) -> bytes:
    """A ``TPM2B`` of exactly *size* bytes, as ``get2b_fixed``."""
    data = _sized_max(r, size)
    if len(data) != size:
        raise ValueError(f"a sized field of {len(data)} bytes, not {size}")
    return data


def _decode(field: str, limit: int) -> bytes:
    """The bytes of a base64 field, which must be exactly their own encoding."""
    if len(field) > 4 * ((limit + 2) // 3):
        raise ValueError("a base64 field longer than its limit")
    raw = base64.b64decode(field, validate=True)
    if base64.b64encode(raw).decode("ascii") != field or len(raw) > limit:
        raise ValueError("not the base64 of its bytes, or out of size")
    return raw


def _point(ak: bytes) -> tuple[int, int]:
    """Return the public point of a ``TPMT_PUBLIC``: ECC, ECDSA with SHA-256, NIST P-256.

    Follows ``tpm_public_parse`` and ``ak_is_p256_ecdsa`` of shirudo: the name
    algorithm is SHA-256, the auth policy is empty or 32 bytes, a symmetric
    algorithm is absent or AES-128-CFB, there is no KDF, and the coordinates are
    32 bytes each. The object attributes are what the node declares and are not
    checked, as in ``shirudo-quote-check``.
    """
    r = _Reader(ak)
    kind = r.u16()
    if r.u16() != _TPM_ALG_SHA256:
        raise ValueError("a key not named with SHA-256")
    r.u32()  # objectAttributes
    if len(_sized_max(r, 32)) not in (0, 32):
        raise ValueError("an auth policy that is neither empty nor 32 bytes")
    symmetric = r.u16()
    bits = mode = 0
    if symmetric != _TPM_ALG_NULL:
        bits, mode = r.u16(), r.u16()
    scheme = r.u16()
    scheme_hash = r.u16() if scheme != _TPM_ALG_NULL else 0
    if kind != _TPM_ALG_ECC:
        raise ValueError("not an ECC key")
    curve = r.u16()
    if r.u16() != _TPM_ALG_NULL:
        raise ValueError("a KDF")
    x, y = _sized_exact(r, 32), _sized_exact(r, 32)
    r.done()
    if symmetric != _TPM_ALG_NULL and (symmetric, bits, mode) != (_TPM_ALG_AES, 128, _TPM_ALG_CFB):
        raise ValueError("a symmetric algorithm other than AES-128-CFB")
    if (scheme, scheme_hash, curve) != (_TPM_ALG_ECDSA, _TPM_ALG_SHA256, _TPM_ECC_NIST_P256):
        raise ValueError("not ECDSA with SHA-256 on NIST P-256")
    return int.from_bytes(x, "big"), int.from_bytes(y, "big")


def _name(ak: bytes) -> bytes:
    return struct.pack(">H", _TPM_ALG_SHA256) + hashlib.sha256(ak).digest()


def _qualified_name(ak: bytes) -> bytes:
    """The key's qualified name under the endorsement hierarchy, the quote's signer."""
    parent = struct.pack(">I", _TPM_RH_ENDORSEMENT)
    return struct.pack(">H", _TPM_ALG_SHA256) + hashlib.sha256(parent + _name(ak)).digest()


def _attest(attest: bytes) -> tuple[bytes, bytes, int, int]:
    """Return signer, qualifying data, reset count and clock of a keepalive quote.

    Follows ``tpm_attest_parse`` and ``attest_is_keepalive_quote`` of shirudo: a
    signer of at most 34 bytes, qualifying data of at most 64, one SHA-256
    selection of exactly three bytes with no PCR set, and a 32-byte PCR digest.
    """
    r = _Reader(attest)
    if r.u32() != _TPM_GENERATED or r.u16() != _TPM_ST_ATTEST_QUOTE:
        raise ValueError("not a quote")
    signer, extra = _sized_max(r, _NAME_LEN), _sized_max(r, 64)
    clock, reset = r.u64(), r.u32()
    r.u32()  # restartCount
    r.u8()  # safe
    r.u64()  # firmwareVersion
    if r.u32() != 1 or r.u16() != _TPM_ALG_SHA256 or r.u8() != _PCR_SELECT_LEN:
        raise ValueError("not one SHA-256 selection of three bytes")
    if any(r.take(_PCR_SELECT_LEN)):
        raise ValueError("a PCR is selected")
    _sized_exact(r, 32)  # pcrDigest
    r.done()
    return signer, extra, reset, clock


def _signature(sig: bytes) -> tuple[int, int]:
    """Return ``r`` and ``s`` of a ``TPMT_SIGNATURE``, as ``tpm_ecdsa_signature_parse``."""
    s = _Reader(sig)
    if s.u16() != _TPM_ALG_ECDSA or s.u16() != _TPM_ALG_SHA256:
        raise ValueError("not ECDSA with SHA-256")
    sig_r, sig_s = _sized_exact(s, 32), _sized_exact(s, 32)
    s.done()
    return int.from_bytes(sig_r, "big"), int.from_bytes(sig_s, "big")


def check_quote(quote: Quote, body_sha256: str) -> Verdict:
    """Return the verdict of ``shirudo-quote-check`` on one row: the first check that fails.

    ``ok`` proves that the body whose SHA-256 is *body_sha256* is unchanged since
    the key in ``quote.ak`` signed it, not that the key lives in a TPM, and not
    that the key is one the reader accepts for a host.
    """
    try:
        attest = _decode(quote.attest, _MAX_ATTEST)
        sig = _decode(quote.sig, _MAX_SIG)
        ak = _decode(quote.ak, _MAX_AK)
        if not _HEX64.fullmatch(body_sha256):
            raise ValueError("body_sha256 is not 64 hex digits")
        wanted = bytes.fromhex(body_sha256)
        x, y = _point(ak)
        signer, extra, _, _ = _attest(attest)
    except (ValueError, binascii.Error):
        return "malformed"
    if signer != _qualified_name(ak):
        return "bad_signature"
    try:
        sig_r, sig_s = _signature(sig)
    except ValueError:
        return "malformed"
    try:
        key = ec.EllipticCurvePublicNumbers(x, y, ec.SECP256R1()).public_key()
        key.verify(encode_dss_signature(sig_r, sig_s), attest, ec.ECDSA(hashes.SHA256()))
    except (InvalidSignature, ValueError):  # a point off the curve verifies nothing
        return "bad_signature"
    if extra != wanted:
        return "body_mismatch"
    return "ok"


def quote_clock(quote: Quote) -> tuple[int, int]:
    """Return ``(resetCount, clock)`` of a quote, which orders the keepalives of one node."""
    _, _, reset, clock = _attest(_decode(quote.attest, _MAX_ATTEST))
    return reset, clock


_HASH = re.compile(r"[0-9a-f]{64}")
#: The type of each key: ``hash`` is 64 lowercase hex digits, ``int`` an integer with
#: no sign, fraction or exponent, ``ints`` an array of them; ``?`` allows ``null``.
_TYPES = {
    "schema": "str", "boot_id": "str", "version_id": "hash", "config_root": "hash?",
    "kernel_release": "str", "image_id": "str?", "image_version": "str?", "image_root": "hash?",
    "verdict": "str", "cond": "int", "flags": "int", "tamper": "ints?", "integrity": "ints?",
    "tree_id": "str?", "generation": "int?", "base_seq": "int?", "last_seq": "int?",
    "base_root": "hash?", "projection_root": "hash?", "mask": "str?", "set_sha256": "hash",
    "count": "int", "not_ok": "int",
}  # fmt: skip


def _plain(value: object) -> bool:
    """A string this module writes: printable ASCII that JSON carries without an escape.

    shirudo's own bodies are UTF-8 and may hold more. The simulator never needs
    more, and a body without escapes has one encoding only, so its hash is the
    same whichever JSON writer made it.
    """
    return isinstance(value, str) and all(0x20 <= ord(c) < 0x7F and c not in '"\\' for c in value)


def _unsigned(value: object) -> bool:
    return type(value) is int and value >= 0


def _typed(key: str, value: object) -> bool:
    kind = _TYPES[key]
    if kind.endswith("?"):
        if value is None:
            return True
        kind = kind[:-1]
    if kind == "str":
        return _plain(value)
    if kind == "hash":
        return isinstance(value, str) and _HASH.fullmatch(value) is not None
    if kind == "int":
        return _unsigned(value)
    return isinstance(value, list) and all(_unsigned(v) for v in value)


def encode_body(fields: Mapping[str, Any]) -> bytes:
    """Return the body bytes: compact JSON, the 23 keys in their order, at most 4095 bytes.

    Every value must have the type the format gives its key. Strings are
    limited to printable ASCII without a quote or a backslash (see ``_plain``).
    """
    missing = [k for k in BODY_KEYS if k not in fields]
    if missing or len(fields) != len(BODY_KEYS):
        raise KeepaliveError(f"a body has exactly the keys of the format; missing {missing}")
    if fields["schema"] != SCHEMA:
        raise KeepaliveError(f"schema is not {SCHEMA}")
    wrong = [k for k in BODY_KEYS if not _typed(k, fields[k])]
    if wrong:
        raise KeepaliveError(f"values not of the type of their key: {', '.join(wrong)}")
    body = json.dumps({k: fields[k] for k in BODY_KEYS}, separators=(",", ":")).encode("ascii")
    if len(body) > MAX_BODY_BYTES:
        raise KeepaliveError(f"a body is at most {MAX_BODY_BYTES} bytes, this one {len(body)}")
    return body


def parse_body(body: bytes) -> dict[str, Any]:
    """Return the fields of a body, refusing one that is not exactly in the format."""
    if len(body) > MAX_BODY_BYTES:
        raise KeepaliveError(f"a body is at most {MAX_BODY_BYTES} bytes, this one {len(body)}")

    def no_constant(name: str) -> object:
        raise KeepaliveError(f"{name} is not a JSON number")

    try:
        fields = json.loads(body.decode("utf-8"), parse_constant=no_constant)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise KeepaliveError(f"not JSON in UTF-8: {exc}") from exc
    if not isinstance(fields, dict) or tuple(fields) != BODY_KEYS:
        raise KeepaliveError("the keys of a body are the 23 of the format, in their order")
    if encode_body(fields) != body:
        raise KeepaliveError("a body is compact JSON with no blank and no trailing newline")
    return fields


@dataclass(frozen=True)
class HostKey:
    """The attestation key of one simulated host: a software key, never a TPM's."""

    host: str
    _key: ec.EllipticCurvePrivateKey

    @property
    def ak(self) -> bytes:
        """The marshalled ``TPMT_PUBLIC``, in the template of shirudo's attestation key."""
        n = self._key.public_key().public_numbers()
        return (
            struct.pack(">HHI", _TPM_ALG_ECC, _TPM_ALG_SHA256, _AK_ATTRIBUTES)
            + _sized(b"")
            + struct.pack(">HHHHH", _TPM_ALG_NULL, _TPM_ALG_ECDSA, _TPM_ALG_SHA256,
                          _TPM_ECC_NIST_P256, _TPM_ALG_NULL)
            + _sized(n.x.to_bytes(32, "big"))
            + _sized(n.y.to_bytes(32, "big"))
        )  # fmt: skip

    @property
    def name(self) -> str:
        """The key's name in hex, ``000b`` and the SHA-256 of ``ak``: it identifies the node."""
        return _name(self.ak).hex()

    def quote(self, body: bytes, clock_ms: int, reset_count: int = 0) -> Quote:
        """Return the keepalive quote of *body* at TPM clock *clock_ms* (simulated time)."""
        ak = self.ak
        attest = (
            struct.pack(">IH", _TPM_GENERATED, _TPM_ST_ATTEST_QUOTE)
            + _sized(_qualified_name(ak))
            + _sized(hashlib.sha256(body).digest())
            + struct.pack(">QIIBQ", clock_ms, reset_count, 0, 1, 0)
            + struct.pack(">IHB", 1, _TPM_ALG_SHA256, 3) + b"\0\0\0"
            + _sized(hashlib.sha256(b"").digest())
        )  # fmt: skip
        der = self._key.sign(attest, ec.ECDSA(hashes.SHA256(), deterministic_signing=True))
        r, s = decode_dss_signature(der)
        sig = (
            struct.pack(">HH", _TPM_ALG_ECDSA, _TPM_ALG_SHA256)
            + _sized(r.to_bytes(32, "big"))
            + _sized(s.to_bytes(32, "big"))
        )

        def text(raw: bytes) -> str:
            return base64.b64encode(raw).decode("ascii")

        return Quote(text(attest), text(sig), text(ak))


def host_key(seed: int, host: str) -> HostKey:
    """Return the key of *host* in a run with *seed*: the same seed, the same key."""
    digest = hashlib.sha256(f"agentic-datacenter/host-key/1\0{seed}\0{host}".encode()).digest()
    scalar = int.from_bytes(digest, "big") % (_P256_ORDER - 1) + 1
    return HostKey(host, ec.derive_private_key(scalar, ec.SECP256R1()))
