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
