"""`agentic-datacenter gate check` fails a served gate whose service does not answer."""

from __future__ import annotations

import socket

import pytest

from agentic_datacenter.core.cli import main


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@pytest.mark.req("ADC-GOV-008")
def test_the_check_fails_when_nothing_listens(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("ADC_GATE_URL", f"http://127.0.0.1:{_free_port()}")
    assert main(["gate", "check", "http_gate"]) == 1
    assert "gave no usable answer" in capsys.readouterr().out
