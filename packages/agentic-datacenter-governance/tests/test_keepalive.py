"""Host evidence in shirudo's keepalive format, checked without a TPM (ADR 0030).

The vectors under ``tests/fixtures/shirudo/keepalive/`` are shirudo's own, at the
commit in ``SHIRUDO_PIN``. A checker that gives the verdict shirudo-quote-check
gives on them, and on the failure cases its reference names, reads the format the
way shirudo does.
"""

import base64
import hashlib
import json
import struct
from pathlib import Path

import pytest

from agentic_datacenter.governance.keepalive import (
    BODY_KEYS,
    KeepaliveError,
    Quote,
    check_quote,
    encode_body,
    host_key,
    parse_body,
    quote_clock,
)

REPO = Path(__file__).resolve().parents[3]
VECTORS = REPO / "tests/fixtures/shirudo/keepalive"


def rows() -> list[tuple[bytes, Quote, str]]:
    out = []
    for line in (VECTORS / "quotes.tsv").read_text(encoding="utf-8").splitlines():
        name, attest, sig, ak, body_sha256 = line.split("\t")
        out.append(((VECTORS / name).read_bytes(), Quote(attest, sig, ak), body_sha256))
    return out


def sha(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def flip_last(field: str) -> str:
    raw = bytearray(base64.b64decode(field))
    raw[-1] ^= 0x01
    return b64(bytes(raw))


BODY = (VECTORS / "node-a-1.0.0.json").read_bytes()


@pytest.mark.req("ADC-HST-001")
def test_every_pinned_vector_checks() -> None:
    assert len(rows()) == 4
    for body, quote, body_sha256 in rows():
        assert sha(body) == body_sha256
        assert check_quote(quote, body_sha256) == "ok"


@pytest.mark.req("ADC-HST-001")
def test_a_quote_of_another_body_is_a_body_mismatch() -> None:
    (_, quote, _), (other, _, _) = rows()[0], rows()[1]
    assert check_quote(quote, sha(other)) == "body_mismatch"


@pytest.mark.req("ADC-HST-001")
def test_a_changed_signature_or_attest_is_a_bad_signature() -> None:
    _, quote, body_sha256 = rows()[0]
    changed_sig = Quote(quote.attest, flip_last(quote.sig), quote.ak)
    assert check_quote(changed_sig, body_sha256) == "bad_signature"
    # The last byte of attest is in the PCR digest: it parses, and the signature fails.
    changed_attest = Quote(flip_last(quote.attest), quote.sig, quote.ak)
    assert check_quote(changed_attest, body_sha256) == "bad_signature"


@pytest.mark.req("ADC-HST-001")
def test_a_signer_that_is_not_the_qualified_name_of_the_key_is_a_bad_signature() -> None:
    other = host_key(seed=1, host="sup-01")
    body = BODY
    mine = other.quote(body, clock_ms=1_000)
    _, theirs, _ = rows()[0]
    # Their key with my attest: the signer named in attest is not their key.
    assert check_quote(Quote(mine.attest, mine.sig, theirs.ak), sha(body)) == "bad_signature"


@pytest.mark.req("ADC-HST-001")
@pytest.mark.parametrize(
    "quote",
    [
        Quote("", "", ""),
        Quote("not base64!", "AA==", "AA=="),
        Quote("AA", "AA==", "AA=="),  # padding missing
        Quote("AA==\n", "AA==", "AA=="),  # a line break
    ],
)
def test_input_that_does_not_parse_is_malformed(quote: Quote) -> None:
    assert check_quote(quote, sha(BODY)) == "malformed"


@pytest.mark.req("ADC-HST-001")
def test_a_body_hash_that_is_not_64_hex_digits_is_malformed() -> None:
    _, quote, body_sha256 = rows()[0]
    assert check_quote(quote, body_sha256[:-1]) == "malformed"
    assert check_quote(quote, body_sha256.upper()) == "ok"  # either case


@pytest.mark.req("ADC-HST-001")
def test_a_quote_that_selects_a_pcr_is_malformed() -> None:
    """An attestation quote always selects a PCR, so it never passes as a keepalive."""
    _, quote, body_sha256 = rows()[0]
    attest = bytearray(base64.b64decode(quote.attest))
    marker = struct.pack(">IHB", 1, 0x000B, 3) + b"\0\0\0"
    at = attest.index(marker) + len(marker) - 3
    attest[at] = 0x01
    assert check_quote(Quote(b64(bytes(attest)), quote.sig, quote.ak), body_sha256) == "malformed"


@pytest.mark.req("ADC-HST-001")
def test_a_quote_the_simulator_makes_checks_and_a_changed_body_does_not() -> None:
    key = host_key(seed=7, host="sup-01")
    quote = key.quote(BODY, clock_ms=60_000)
    assert check_quote(quote, sha(BODY)) == "ok"
    tampered = BODY.replace(b'"verdict":"ok"', b'"verdict":"tampered"')
    assert tampered != BODY
    assert check_quote(quote, sha(tampered)) == "body_mismatch"


@pytest.mark.req("ADC-HST-002")
def test_every_pinned_body_parses_and_encodes_to_the_same_bytes() -> None:
    for body, _, _ in rows():
        fields = parse_body(body)
        assert list(fields) == list(BODY_KEYS)
        assert fields["schema"] == "shirudo.keepalive/1"
        assert encode_body(fields) == body


@pytest.mark.req("ADC-HST-002")
def test_a_body_without_a_key_or_with_keys_out_of_order_is_refused() -> None:
    fields = parse_body(BODY)
    missing = {k: v for k, v in fields.items() if k != "verdict"}
    with pytest.raises(KeepaliveError, match="verdict"):
        encode_body(missing)
    swapped = dict(reversed(list(fields.items())))
    with pytest.raises(KeepaliveError, match="order"):
        parse_body(json.dumps(swapped, separators=(",", ":")).encode())


@pytest.mark.req("ADC-HST-002")
def test_a_body_that_is_not_compact_or_too_long_is_refused() -> None:
    with pytest.raises(KeepaliveError, match="compact"):
        parse_body(json.dumps(parse_body(BODY)).encode())  # blanks between tokens
    with pytest.raises(KeepaliveError, match="compact"):
        parse_body(BODY + b"\n")
    fields = parse_body(BODY)
    with pytest.raises(KeepaliveError, match="4095"):
        encode_body({**fields, "image_id": "x" * 4096})


@pytest.mark.req("ADC-HST-003")
def test_a_host_key_and_its_quotes_are_a_function_of_seed_and_host() -> None:
    first = host_key(seed=3, host="sup-01")
    again = host_key(seed=3, host="sup-01")
    assert first.name == again.name
    assert first.quote(BODY, clock_ms=5_000) == again.quote(BODY, clock_ms=5_000)
    assert host_key(seed=3, host="agent-01").name != first.name
    assert host_key(seed=4, host="sup-01").name != first.name
    assert first.name.startswith("000b") and len(first.name) == 68


@pytest.mark.req("ADC-HST-003")
def test_the_tpm_clock_of_a_quote_orders_the_keepalives_of_a_host() -> None:
    key = host_key(seed=3, host="sup-01")
    early = key.quote(BODY, clock_ms=5_000)
    late = key.quote(BODY, clock_ms=65_000, reset_count=1)
    assert quote_clock(early) == (0, 5_000)
    assert quote_clock(late) == (1, 65_000)
    assert quote_clock(late) > quote_clock(early)
    _, pinned, _ = rows()[0]
    reset, clock = quote_clock(pinned)  # shirudo's own vector reads too
    assert reset >= 0 and clock >= 0


# --- Structures shirudo's parsers refuse, each with a valid signature ---------------
#
# Each case is built and signed with a software key, so that the only thing wrong
# with it is the one field named. The verdicts are those of ``tpm_public_parse``,
# ``tpm_attest_parse``, ``tpm_ecdsa_signature_parse`` and ``quote_row_check`` in
# shirudo (``util/tpm_wire.c``, ``tools/quote-check/row.c``) at the pinned commit.

ECC, SHA256, ECDSA, NULL, AES, CFB, P256, P384 = 0x23, 0x0B, 0x18, 0x10, 0x06, 0x43, 0x03, 0x04
SIGNER = host_key(seed=11, host="sup-01")
SIGNING = SIGNER._key


def sized(data: bytes) -> bytes:
    return struct.pack(">H", len(data)) + data


def make_ak(
    *,
    kind: int = ECC,
    policy: bytes = b"",
    sym: bytes = struct.pack(">H", NULL),
    scheme: bytes = struct.pack(">HH", ECDSA, SHA256),
    curve: int = P256,
    kdf: int = NULL,
    x: bytes | None = None,
    y: bytes | None = None,
) -> bytes:
    numbers = SIGNING.public_key().public_numbers()
    x = numbers.x.to_bytes(32, "big") if x is None else x
    y = numbers.y.to_bytes(32, "big") if y is None else y
    return (
        struct.pack(">HHI", kind, SHA256, 0x00050072) + sized(policy) + sym + scheme
        + struct.pack(">HH", curve, kdf) + sized(x) + sized(y)
    )  # fmt: skip


def qualified(ak: bytes) -> bytes:
    name = struct.pack(">H", SHA256) + hashlib.sha256(ak).digest()
    return struct.pack(">H", SHA256) + hashlib.sha256(struct.pack(">I", 0x4000000B) + name).digest()


def make_attest(
    ak: bytes,
    *,
    body: bytes = BODY,
    kind: int = 0x8018,
    signer: bytes | None = None,
    extra: bytes | None = None,
    select: bytes = b"\3\0\0\0",
    digest: bytes = hashlib.sha256(b"").digest(),
) -> bytes:
    signer = qualified(ak) if signer is None else signer
    extra = hashlib.sha256(body).digest() if extra is None else extra
    return (
        struct.pack(">IH", 0xFF544347, kind) + sized(signer) + sized(extra)
        + struct.pack(">QIIBQ", 1000, 0, 0, 1, 0)
        + struct.pack(">IH", 1, SHA256) + select + sized(digest)
    )  # fmt: skip


def make_sig(attest: bytes, *, width: int = 32) -> bytes:
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature

    der = SIGNING.sign(attest, ec.ECDSA(hashes.SHA256(), deterministic_signing=True))
    r, s = decode_dss_signature(der)
    return (
        struct.pack(">HH", ECDSA, SHA256)
        + sized(r.to_bytes(width, "big"))
        + sized(s.to_bytes(width, "big"))
    )


def verdict(ak: bytes, attest: bytes, sig: bytes | None = None, body: bytes = BODY) -> str:
    sig = make_sig(attest) if sig is None else sig
    return check_quote(Quote(b64(attest), b64(sig), b64(ak)), sha(body))


@pytest.mark.req("ADC-HST-001")
def test_the_builders_make_a_quote_that_checks() -> None:
    ak = make_ak()
    assert ak == SIGNER.ak
    assert verdict(ak, make_attest(ak)) == "ok"


@pytest.mark.req("ADC-HST-001")
@pytest.mark.parametrize(
    "ak",
    [
        make_ak(policy=b"\0" * 16),  # an auth policy is empty or 32 bytes
        make_ak(curve=P384),
        make_ak(scheme=struct.pack(">H", NULL)),  # no scheme: not ECDSA
        make_ak(scheme=struct.pack(">HH", ECDSA, 0x0C)),  # ECDSA with SHA-384
        make_ak(kdf=SHA256),
        make_ak(sym=struct.pack(">HHH", AES, 256, CFB)),
        make_ak(x=b"\1" * 31),
        make_ak(kind=0x0001),  # RSA
        make_ak() + b"\0",  # trailing bytes
    ],
    ids=["policy16", "p384", "no-scheme", "sha384", "kdf", "aes256", "x31", "rsa", "trailing"],
)
def test_a_key_shirudo_does_not_parse_as_p256_ecdsa_is_malformed(ak: bytes) -> None:
    assert verdict(ak, make_attest(ak)) == "malformed"


@pytest.mark.req("ADC-HST-001")
def test_a_key_with_aes_128_cfb_or_a_32_byte_policy_is_taken() -> None:
    """``tpm_public_parse`` takes both; the quote checker does not ask for more."""
    for ak in (make_ak(sym=struct.pack(">HHH", AES, 128, CFB)), make_ak(policy=b"\7" * 32)):
        assert verdict(ak, make_attest(ak)) == "ok"


@pytest.mark.req("ADC-HST-001")
@pytest.mark.parametrize(
    "change",
    [
        {"signer": b"\0" * 35},  # a name is at most 34 bytes
        {"extra": b"\0" * 65},  # qualifying data is at most 64 bytes
        {"select": b"\4\0\0\0\0"},  # a selection of four bytes, none set
        {"select": b"\2\0\0"},
        {"digest": b"\0" * 31},  # the PCR digest is exactly 32 bytes
        {"kind": 0x8014},  # an NV certification, not a quote
    ],
    ids=["signer35", "extra65", "select4", "select2", "digest31", "nv"],
)
def test_an_attest_shirudo_does_not_parse_as_a_keepalive_quote_is_malformed(
    change: dict[str, object],
) -> None:
    ak = make_ak()
    assert verdict(ak, make_attest(ak, **change)) == "malformed"  # type: ignore[arg-type]


@pytest.mark.req("ADC-HST-001")
def test_qualifying_data_of_another_size_is_a_body_mismatch() -> None:
    ak = make_ak()
    for extra in (b"", b"\0" * 20, b"\0" * 64):
        assert verdict(ak, make_attest(ak, extra=extra)) == "body_mismatch"


@pytest.mark.req("ADC-HST-001")
@pytest.mark.parametrize("width", [31, 33])
def test_a_signature_whose_r_and_s_are_not_32_bytes_is_malformed(width: int) -> None:
    """Check 5: ``get2b_fixed`` takes exactly 32 bytes, so a shortened ``r`` is malformed."""
    ak = make_ak()
    attest = make_attest(ak)
    if width == 31:
        sig = make_sig(attest)
        sig = sig[:4] + sized(sig[7:38]) + sig[38:]  # r without its first byte
    else:
        sig = make_sig(attest, width=33)
    assert verdict(ak, attest, sig) == "malformed"


@pytest.mark.req("ADC-HST-001")
def test_a_signature_of_another_scheme_is_malformed() -> None:
    ak = make_ak()
    attest = make_attest(ak)
    sig = make_sig(attest)
    assert verdict(ak, attest, struct.pack(">H", 0x0014) + sig[2:]) == "malformed"  # RSASSA


@pytest.mark.req("ADC-HST-001")
def test_the_first_check_that_fails_decides() -> None:
    ak = make_ak()
    # Check 3 (attest) before check 6 (signature): a bad signature on a bad attest.
    bad_attest = make_attest(ak, digest=b"\0" * 31)
    assert verdict(ak, bad_attest, make_sig(make_attest(ak))) == "malformed"
    # Check 4 (signer) before check 5 (signature parse).
    foreign = make_attest(ak, signer=b"\0" * 34)
    assert verdict(ak, foreign, b"\0\0") == "bad_signature"
    # Check 2 (key) before check 3 (attest).
    assert verdict(make_ak(curve=P384), bad_attest) == "malformed"


@pytest.mark.req("ADC-HST-001")
def test_a_key_that_is_no_point_of_the_curve_is_a_bad_signature() -> None:
    ak = make_ak(x=b"\0" * 31 + b"\1", y=b"\0" * 31 + b"\1")
    assert verdict(ak, make_attest(ak)) == "bad_signature"


@pytest.mark.req("ADC-HST-001")
def test_fields_beyond_their_size_are_malformed() -> None:
    ak = make_ak()
    attest = make_attest(ak)
    sig = make_sig(attest)
    long = Quote(b64(b"\0" * 1025), b64(sig), b64(ak))
    assert check_quote(long, sha(BODY)) == "malformed"
    long_sig = Quote(b64(attest), b64(sig + b"\0" * 100), b64(ak))
    assert check_quote(long_sig, sha(BODY)) == "malformed"
    long_ak = Quote(b64(attest), b64(sig), b64(ak + b"\0" * 450))
    assert check_quote(long_ak, sha(BODY)) == "malformed"


@pytest.mark.req("ADC-HST-001")
def test_a_body_hash_with_a_blank_is_malformed() -> None:
    ak = make_ak()
    attest = make_attest(ak)
    quote = Quote(b64(attest), b64(make_sig(attest)), b64(ak))
    assert check_quote(quote, sha(BODY)[:62] + "  ") == "malformed"
    assert check_quote(quote, " " + sha(BODY)[1:]) == "malformed"


@pytest.mark.req("ADC-HST-002")
@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("cond", 5461.0),
        ("cond", -1),
        ("cond", True),
        ("verdict", 5),
        ("verdict", "o\0k"),
        ("image_id", "fléet"),
        ("image_id", 'a"b'),
        ("version_id", "D" * 64),
        ("set_sha256", None),
        ("tamper", [0, 1.5]),
        ("boot_id", None),
    ],
)
def test_a_value_not_of_the_type_of_its_key_is_refused(key: str, value: object) -> None:
    fields = {**parse_body(BODY), key: value}
    with pytest.raises(KeepaliveError, match=key):
        encode_body(fields)


@pytest.mark.req("ADC-HST-002")
@pytest.mark.parametrize(
    "text",
    [b'"cond":NaN', b'"cond":Infinity', b'"image_id":"\\ud800"', b'"image_id":"a\\u0000b"'],
)
def test_a_body_with_a_constant_a_surrogate_or_a_nul_is_refused(text: bytes) -> None:
    key = text.split(b":")[0]
    start = BODY.index(key + b":")
    end = BODY.index(b",", start)
    with pytest.raises(KeepaliveError):
        parse_body(BODY[:start] + text + BODY[end:])
