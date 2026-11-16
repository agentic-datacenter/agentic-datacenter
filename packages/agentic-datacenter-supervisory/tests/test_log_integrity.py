"""Append-only logs (ADC-SUP-002)."""

import pytest

from agentic_datacenter.core.scheduler import Kernel
from agentic_datacenter.supervisory.logs import AppendOnlyLog, LogIntegrityError


def log() -> tuple[Kernel, AppendOnlyLog]:
    kernel = Kernel(seed=1)
    return kernel, AppendOnlyLog(kernel, "audit")


@pytest.mark.req("ADC-SUP-002")
def test_entries_are_numbered_timed_and_chained() -> None:
    kernel, audit = log()
    first = audit.append("login", actor="ola")
    kernel.run_for(2000)
    second = audit.append("write", actor="ola", tag="x")
    assert (first["seq"], second["seq"]) == (0, 1)
    assert (first["time_ms"], second["time_ms"]) == (0, 2000)
    assert second["prev"] == first["hash"] and len(str(first["hash"])) == 64
    assert audit.verify() and len(audit) == 2


@pytest.mark.req("ADC-SUP-002")
@pytest.mark.parametrize("attempt", ["modify", "delete", "truncate"])
def test_an_attempt_to_change_the_log_is_rejected_and_logged(attempt: str) -> None:
    _, audit = log()
    audit.append("write", actor="ola", tag="x")
    audit.append("write", actor="ola", tag="y")
    before = audit.entries()
    with pytest.raises(LogIntegrityError, match=attempt):
        if attempt == "modify":
            audit.modify(0, "mallory", {"actor": "nobody"})
        elif attempt == "delete":
            audit.delete(1, "mallory")
        else:
            audit.truncate(0, "mallory")
    after = audit.entries()
    assert after[:2] == before, "nothing that was written has changed"
    assert len(after) == 3 and after[2]["kind"] == "integrity_violation"
    assert after[2]["attempt"] == attempt and after[2]["actor"] == "mallory"
    assert audit.verify()


@pytest.mark.req("ADC-SUP-002")
def test_what_the_log_returns_is_a_copy() -> None:
    _, audit = log()
    audit.append("write", actor="ola")
    got = audit.entries()
    got[0]["actor"] = "nobody"
    got.clear()
    assert audit.entries()[0]["actor"] == "ola"


@pytest.mark.req("ADC-SUP-002")
def test_tampering_behind_the_interface_breaks_the_chain() -> None:
    _, audit = log()
    audit.append("write", actor="ola")
    audit.append("write", actor="eva")
    audit._entries[0]["actor"] = "nobody"  # noqa: SLF001
    assert not audit.verify()


def test_reserved_fields_cannot_be_supplied() -> None:
    _, audit = log()
    with pytest.raises(ValueError, match="seq"):
        audit.append("write", seq=7)


def test_log_is_part_of_the_state_and_comes_back_from_a_snapshot() -> None:
    kernel, audit = log()
    audit.append("write", actor="ola")
    saved, digest = kernel.snapshot(), kernel.state_hash()
    audit.append("write", actor="eva")
    assert kernel.state_hash() != digest
    kernel.restore(saved)
    assert len(audit) == 1 and kernel.state_hash() == digest and audit.verify()
