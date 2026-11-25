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
    "service_verdict", "service_decision_id", "service_receipt", "members",
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
    points: Any, overview: Any, time_ms: int, epoch: str = EPOCH
) -> dict[str, JsonValue]:
    """Return the read-only sample of the plant a request carries with ``ADC_GATE_CONTEXT=1``.

    *points* is the point database and *overview* the supervisory overview
    over it. Work permits are not modelled as points in this version; the
    context says so rather than leave them out unsaid.
    """
    tags = sorted(points.tags())
    out: dict[str, JsonValue] = {
        "schema": CONTEXT_SCHEMA,
        "read_only": True,
        "resolution_source": RESOLUTION_SOURCE,
        "time_ms": int(time_ms),
        "observed_at": utc(time_ms, epoch),
        "time_anchor": epoch,
    }
    for group, patterns in CONTEXT_POINTS.items():
        chosen = [t for t in tags if any(re.search(p, t) for p in patterns)]
        rows: list[JsonValue] = []
        for tag in chosen:
            r = points.read(tag)
            rows.append({
                "tag": r.tag, "value": r.value, "unit": r.unit, "quality": r.quality,
                "time_ms": r.time_ms, "observed_at": utc(r.time_ms, epoch),
            })  # fmt: skip
        out[group] = rows
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

    @property
    def ok(self) -> bool:
        """Every receipt matched a decision on record, and the record's own reference holds."""
        return not (self.mismatched or self.unknown or self.unbound_records)

    def as_dict(self) -> dict[str, JsonValue]:
        """Return the report for printing."""
        return {
            "ok": self.ok,
            "matched": list(self.matched),
            "mismatched": {k: list(v) for k, v in self.mismatched.items()},
            "unknown_correlation_ids": list(self.unknown),
            "decisions_without_receipt": list(self.without_receipt),
            "records_whose_action_ref_does_not_hold": list(self.unbound_records),
        }


def merge_receipts(lines: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """Return the receipts by correlation id; later lines for one id add to it.

    A system may write one line when it decides and another when it is told
    the outcome.
    """
    out: dict[str, dict[str, Any]] = {}
    for line in lines:
        key = str(line.get("correlation_id", ""))
        out.setdefault(key, {}).update(dict(line))
    return out


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
) -> ReceiptReport:
    """Check receipts against the decision records of a run.

    Each receipt names a ``correlation_id`` and may give ``action_ref``,
    ``verdict`` (a word of the system's own is read as the verdict it means,
    with *read_verdict*), ``outcome`` and ``decision_id``. Each that it gives
    must be what the record holds. Each record's own ``action_ref`` is made
    again from the record, so a record changed after the run is found too.
    No signature is checked: that is the system's own verifier's work.
    """
    report = ReceiptReport()
    by_id: dict[str, Mapping[str, Any]] = {}
    details: dict[str, Mapping[str, Any]] = {}
    for record in records:
        for detail in _correlated(record):
            cid = str(detail["correlation_id"])
            by_id[cid], details[cid] = record, detail
            again = action_ref(
                str(detail.get("session", "")), str(record["proposal_id"]),
                str(record["contract_id"]), record.get("arguments") or {},
                str(record["principal"]), int(record["time_ms"]),
            )  # fmt: skip
            if again != detail.get("action_ref"):
                report.unbound_records.append(cid)
    merged = merge_receipts(receipts)
    for cid, receipt in merged.items():
        if cid not in by_id:
            report.unknown.append(cid)
            continue
        record, detail = by_id[cid], details[cid]
        # A member of a chain is judged on its own verdict; the outcome is the record's.
        decided = detail.get("verdict", record.get("verdict"))
        wrong = []
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
            report.mismatched[cid] = wrong
        else:
            report.matched.append(cid)
    report.without_receipt = [cid for cid in by_id if cid not in merged]
    return report
