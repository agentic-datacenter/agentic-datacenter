"""The local command starter can be used without a service or an SDK."""

import shlex
import sys
from pathlib import Path

import pytest

from agentic_datacenter.core.cli import main
from agentic_datacenter.governance.bindings.http_gate import CommandGate
from agentic_datacenter.governance.gate import (
    AuthenticatedActor,
    BoundedWrite,
    PremiseResult,
    PremiseSnapshot,
    Proposal,
    Verdict,
)

REPO = Path(__file__).resolve().parents[2]
ADAPTER = REPO / "examples/command-gate/adapter.py"
COMMAND = shlex.join([sys.executable, str(ADAPTER)])


def test_the_starter_passes_the_cli_interface_check(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert ADAPTER.is_file()
    monkeypatch.chdir(REPO)
    monkeypatch.setenv("ADC_GATE_COMMAND", COMMAND)
    assert main(["gate", "check", "command_gate"]) == 0


@pytest.mark.parametrize(
    ("approval", "holds", "verdict", "approvers"),
    [
        ("none", True, Verdict.ALLOW, 0),
        ("one_operator", True, Verdict.VERIFY, 1),
        ("two_person", True, Verdict.VERIFY, 2),
        ("two_person", None, Verdict.ABSTAIN, 0),
        ("none", False, Verdict.DENY, 0),
    ],
)
def test_the_starter_preserves_approval_count_and_unknown_evidence(
    approval: str, holds: bool | None, verdict: Verdict, approvers: int
) -> None:
    gate = CommandGate(COMMAND)
    decision = gate.evaluate(
        Proposal("example", "chw.set_supply_setpoint.v1", {"setpoint_c": 18.5}),
        PremiseSnapshot(
            time_ms=1000,
            contract_known=True,
            approval=approval,
            writes=(BoundedWrite("cooling.chw_plant[CHW].chws_sp_c", 18.5, 18.0),),
            premises=(PremiseResult("temperature_ok", holds, "fixture"),),
        ),
        AuthenticatedActor("fixture-agent", "fixture-credential"),
    )
    assert decision.verdict is verdict
    assert decision.required_approvers == approvers
