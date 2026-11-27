"""What a governance system outside this project needs to work with it (ADR 0036).

Three things, none of which changes what a gate decides or how a run is judged:

- **Correlation.** Every ``evaluate`` request and its ``outcome`` message carry
  the same ``correlation_id``, and a content-addressed ``action_ref``: the
  SHA-256 of the proposed action in canonical JSON. A system that issues a
  receipt binds it to both, and the decision record keeps both.
- **A fixed time anchor.** Simulated time is milliseconds from the start of the
  run. ``issued_at`` and ``observed_at`` give the same instant as UTC from a
  fixed epoch, so a library that checks time-bounded evidence can be given a
  date. The epoch is fixed, never the wall clock, so a run is the same run.
- **Plant context, read-only and optional.** With ``ADC_GATE_CONTEXT=1`` a
  request also carries a sample of the plant: temperatures, load, interlocks,
  margins and alarms, each point with its value, unit, quality and simulated
  time. It is what the simulator's point database held, not attested by any
  sensor.

:func:`verify_receipts` checks, locally and without keys, that the receipts a
system exported match the proposals and outcomes the run recorded.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

from agentic_datacenter.core.state import JsonValue

#: The UTC instant simulated time 0 is given as, unless ``ADC_GATE_EPOCH`` says another.
EPOCH = "2026-01-01T00:00:00Z"
CONTEXT_SCHEMA = "agentic_datacenter.context/1"
#: Where the values of the context come from: the simulator's own point database,
#: read as an operator's screen would show it. Not attested by a sensor.
RESOLUTION_SOURCE = "simulated_point_database"
#: The points a context holds, by group: a pattern over the tag.
CONTEXT_POINTS: Mapping[str, tuple[str, ...]] = {
    "temperatures": (r"\.supply_air_c$", r"^cooling\.chw_plant\[[^\]]+\]\.chws_c$"),
    "load": (
        r"^electrical\.it_load\[[^\]]+\]\.demand_kw$",
        r"^cooling\.chw_plant\[[^\]]+\]\.load_kw$",
    ),
    "interlocks": (
        r"\.alarm_lockout$",
        r"^cooling\.chw_plant\[[^\]]+\]\.ch\d+_state$",
        r"^electrical\.genset\[[^\]]+\]\.state$",
        r"^electrical\.power_train\[[^\]]+\]\.state$",
    ),
}  # fmt: skip
#: What a decision record keeps of a gate's own detail, when the gate gives any of it.
GATE_DETAIL_KEPT = (
    "served_by", "session", "correlation_id", "action_ref", "issued_at",
    "service_verdict", "answered_verdict", "service_decision_id", "service_receipt", "members",
    "receipt_signature",
)  # fmt: skip
#: The fields of a receipt that are compared with the record, when the receipt gives them.
RECEIPT_FIELDS = ("action_ref", "verdict", "outcome", "decision_id")
#: The most of one receipt object kept on a decision.
MAX_RECEIPT_BYTES = 16 * 1024
_ISO = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z")


def parse_epoch(text: str) -> datetime:
    """Return the UTC instant of an epoch written as ``YYYY-MM-DDTHH:MM:SS[.fff]Z``.

    Raises:
        ValueError: If *text* is not of that form.
    """
    if not _ISO.fullmatch(text):
        raise ValueError(f"not a UTC instant of the form 2026-01-01T00:00:00Z: {text!r}")
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)


def utc(time_ms: int, epoch: str = EPOCH) -> str:
    """Return simulated *time_ms* as a UTC instant, counted from *epoch*, to the millisecond."""
    instant = parse_epoch(epoch) + timedelta(milliseconds=int(time_ms))
    return instant.strftime("%Y-%m-%dT%H:%M:%S.") + f"{instant.microsecond // 1000:03d}Z"


def canonical_json(value: Any) -> bytes:
    """Return *value* as canonical JSON: keys sorted, no whitespace, UTF-8."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False
    ).encode("utf-8")


def action_ref(
    session: str,
    proposal_id: str,
    contract_id: str,
    arguments: Mapping[str, JsonValue],
    principal: str,
    time_ms: int,
) -> str:
    """Return the content address of one proposed action: ``sha256:`` and 64 hex digits.

    Made from what the request and the decision record both hold, so anyone
    with the record can make it again.
    """
    preimage = {
        "session": session,
        "proposal_id": proposal_id,
        "contract_id": contract_id,
        "arguments": dict(arguments),
        "principal": principal,
        "time_ms": int(time_ms),
    }
    return "sha256:" + hashlib.sha256(canonical_json(preimage)).hexdigest()


def correlation_id(session: str, proposal_id: str) -> str:
    """Return the identifier an ``evaluate`` request and its ``outcome`` message share."""
    return f"{session}/{proposal_id}"


def plant_context(
    points: Any,
    overview: Any,
    time_ms: int,
    epoch: str = EPOCH,
    spoofed: Mapping[str, JsonValue] | None = None,
) -> dict[str, JsonValue]:
    """Return the read-only sample of the plant a request carries with ``ADC_GATE_CONTEXT=1``.

    *points* is the point database and *overview* the supervisory overview
    over it. Work permits are not modelled as points in this version; the
    context says so rather than leave them out unsaid.

    Each reading is signed by its source, the plant module that owns the
    point, and ``sources`` holds their public keys (ADR 0041). *spoofed* maps
    a tag to a value put in its place by someone on the network: that row
    names the source and is signed by someone else.
    """
    from agentic_datacenter.governance import attest  # noqa: PLC0415 - attest imports this module

    tags = sorted(points.tags())
    out: dict[str, JsonValue] = {
        "schema": CONTEXT_SCHEMA,
        "read_only": True,
        "resolution_source": RESOLUTION_SOURCE,
        "time_ms": int(time_ms),
        "observed_at": utc(time_ms, epoch),
        "time_anchor": epoch,
    }
    names: set[str] = set()
    for group, patterns in CONTEXT_POINTS.items():
        chosen = [t for t in tags if any(re.search(p, t) for p in patterns)]
        rows: list[JsonValue] = []
        for tag in chosen:
            r = points.read(tag)
            row: dict[str, JsonValue] = {
                "tag": r.tag, "value": r.value, "unit": r.unit, "quality": r.quality,
                "time_ms": r.time_ms, "observed_at": utc(r.time_ms, epoch),
            }  # fmt: skip
            false = spoofed is not None and tag in spoofed
            if false:
                assert spoofed is not None
                row = {**row, "value": spoofed[tag], "quality": "good", "time_ms": int(time_ms),
                       "observed_at": utc(time_ms, epoch)}  # fmt: skip
            rows.append(attest.signed_reading(row, attest.INTRUDER if false else None))
            names.add(attest.source_of(tag))
        out[group] = rows
    out["sources"] = [attest.source_record(name) for name in sorted(names)]
    out["redundancy"] = {
        name: {"available": m.available, "required": m.required, "level": m.level_name,
               "quality": m.quality}
        for name, m in overview.redundancy().items()
    }  # fmt: skip
    out["alarms"] = [dict(asdict(a)) for a in overview.active_alarms()]
    out["permits"] = {"modelled": False, "items": []}
    return out


def receipt_kept(receipt: object) -> JsonValue:
    """Return a receipt a service gave with its answer as it is kept, or None if it is not kept.

    An object of at most :data:`MAX_RECEIPT_BYTES` in canonical JSON is kept
    as given; anything else is not.
    """
    if not isinstance(receipt, dict):
        return None
    try:
        size = len(canonical_json(receipt))
    except (TypeError, ValueError):
        return None
    return receipt if size <= MAX_RECEIPT_BYTES else None


@dataclass
class ReceiptReport:
    """What :func:`verify_receipts` found."""

    matched: list[str] = field(default_factory=list)
    mismatched: dict[str, list[str]] = field(default_factory=dict)
    unknown: list[str] = field(default_factory=list)
    without_receipt: list[str] = field(default_factory=list)
    unbound_records: list[str] = field(default_factory=list)
    #: Correlation ids by what was found of their receipts' signatures, when keys
    #: were given: every line verified, a line without a signature, a line whose
    #: signature does not verify.
    signed: list[str] = field(default_factory=list)
    unsigned: list[str] = field(default_factory=list)
    bad_signature: list[str] = field(default_factory=list)
    signatures_checked: bool = False

    @property
    def ok(self) -> bool:
        """Every receipt matched a decision on record, and the record's own reference holds."""
        return not (self.mismatched or self.unknown or self.unbound_records or self.bad_signature)

    def as_dict(self) -> dict[str, JsonValue]:
        """Return the report for printing."""
        return {
            "ok": self.ok,
            "matched": list(self.matched),
            "mismatched": {k: list(v) for k, v in self.mismatched.items()},
            "unknown_correlation_ids": list(self.unknown),
            "decisions_without_receipt": list(self.without_receipt),
            "records_whose_action_ref_does_not_hold": list(self.unbound_records),
            **(
                {
                    "signatures": {
                        "verified": list(self.signed),
                        "not_signed": list(self.unsigned),
                        "failed": list(self.bad_signature),
                    }
                }
                if self.signatures_checked
                else {}
            ),
        }


def merge_receipts(
    lines: Iterable[Mapping[str, Any]],
) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]]]:
    """Return the receipts by correlation id, and the fields two lines of one id disagree on.

    A system may write one line when it decides and another when it is told
    the outcome. A later line adds fields; it never replaces one.
    """
    out: dict[str, dict[str, Any]] = {}
    conflicts: dict[str, list[str]] = {}
    for line in lines:
        key = str(line.get("correlation_id", ""))
        merged = out.setdefault(key, {})
        for field_name, value in line.items():
            if field_name == "signature":
                continue  # each line carries its own
            if field_name in merged and merged[field_name] != value:
                conflicts.setdefault(key, []).append(f"conflicting {field_name}")
            else:
                merged[field_name] = value
    return out, conflicts


def _correlated(record: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """Return the correlated details of a record: its own, or each member's of a chain."""
    detail = record.get("gate_detail")
    if not isinstance(detail, Mapping):
        return []
    found = [detail] if "correlation_id" in detail else []
    members = detail.get("members")
    if isinstance(members, list):
        found += [m for m in members if isinstance(m, Mapping) and "correlation_id" in m]
    return found


def verify_receipts(
    records: Sequence[Mapping[str, Any]],
    receipts: Iterable[Mapping[str, Any]],
    read_verdict: Any = None,
    public_keys: Sequence[str] = (),
    verifier: Any = None,
) -> ReceiptReport:
    """Check receipts against the decision records of a run.

    Each receipt names a ``correlation_id`` and must give ``action_ref`` and
    ``verdict`` (a word of the system's own is read as the verdict it means,
    with *read_verdict*); it may give ``outcome`` and ``decision_id``. Each
    must be what the record holds; the verdict is compared with the one the
    service answered. Each record's own ``action_ref`` is made again from the
    record, so a record whose action was changed is found. That the verdict
    and outcome on record are those of the run is for the evidence bundle's
    manifest to show (``scenario verify``).

    With *public_keys*, raw Ed25519 public keys in base64, the signature of
    each receipt line is checked too: over the line without its ``signature``,
    as canonical JSON (ADR 0041). A line whose signature does not verify fails
    the check; one without a signature is listed. Without keys no signature is
    checked.

    *verifier* is the system's own check of a receipt, for a signature scheme
    or a canonical form other than that: a function that takes one receipt
    line and returns whether it verifies. Every line is then put to it, and
    one it refuses fails the check.
    """
    from agentic_datacenter.governance import attest  # noqa: PLC0415 - attest imports this module

    report = ReceiptReport()
    receipts = list(receipts)
    if verifier is not None:
        report.signatures_checked = True
        refused = [str(line.get("correlation_id", "")) for line in receipts if not verifier(line)]
        every = {str(line.get("correlation_id", "")) for line in receipts}
        report.bad_signature = sorted(set(refused))
        report.signed = sorted(every - set(refused))
    elif public_keys:
        report.signatures_checked = True
        found: dict[str, set[str]] = {}
        for line in receipts:
            state = attest.receipt_signature(line, public_keys)
            found.setdefault(str(line.get("correlation_id", "")), set()).add(state)
        for cid, states in found.items():
            if attest.FAILED in states:
                report.bad_signature.append(cid)
            elif attest.NOT_SIGNED in states:
                report.unsigned.append(cid)
            else:
                report.signed.append(cid)
    by_id: dict[str, Mapping[str, Any]] = {}
    details: dict[str, Mapping[str, Any]] = {}
    for record in records:
        for detail in _correlated(record):
            cid = str(detail["correlation_id"])
            if cid in by_id:
                report.mismatched.setdefault(cid, []).append("correlation_id on two records")
            by_id[cid], details[cid] = record, detail
            again = action_ref(
                str(detail.get("session", "")), str(record["proposal_id"]),
                str(record["contract_id"]), record.get("arguments") or {},
                str(record["principal"]), int(record["time_ms"]),
            )  # fmt: skip
            if again != detail.get("action_ref"):
                report.unbound_records.append(cid)
    merged, conflicts = merge_receipts(receipts)
    for cid, receipt in merged.items():
        if cid not in by_id:
            report.unknown.append(cid)
            continue
        record, detail = by_id[cid], details[cid]
        # The service is judged on the verdict it answered, a member of a chain on its own.
        decided = detail.get("answered_verdict", detail.get("verdict", record.get("verdict")))
        wrong = list(conflicts.get(cid, []))
        for required in ("action_ref", "verdict"):
            if required not in receipt:
                wrong.append(f"no {required}")
        if "action_ref" in receipt and receipt["action_ref"] != detail.get("action_ref"):
            wrong.append("action_ref")
        if "verdict" in receipt:
            given = receipt["verdict"]
            meant = read_verdict(given) if read_verdict is not None else None
            word = meant.value if meant is not None else str(given).upper()
            if word != decided:
                wrong.append("verdict")
        if "outcome" in receipt and str(receipt["outcome"]) != record.get("outcome"):
            wrong.append("outcome")
        if "decision_id" in receipt and str(receipt["decision_id"]) != detail.get(
            "service_decision_id"
        ):
            wrong.append("decision_id")
        if wrong:
            report.mismatched.setdefault(cid, []).extend(wrong)
        elif cid not in report.mismatched:
            report.matched.append(cid)
    report.without_receipt = [cid for cid in by_id if cid not in merged]
    return report
