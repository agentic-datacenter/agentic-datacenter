"""The plant interface changes no card (ADR 0029, ADC-PLT-001).

The cards under ``cards_before_plant_interface/`` were made by the code as it
was before the harness reached the plant through the interface. The same runs
must give the same cards, byte for byte, but for the ``oracle`` hash of the
benchmark version: that is the hash of the harness's source, which the
refactor changes by construction (ADR 0029, open question 1, option d).

    python tests/bench/test_plant_interface_cards.py   # remake them; only on purpose
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings import static_allowlist
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.bench import run_benchmark

REPO = Path(__file__).resolve().parents[2]
CARDS = Path(__file__).parent / "cards_before_plant_interface"
GATES = {"null_gate": lambda contracts: NullGate(), "static_allowlist": static_allowlist.create}
AGENTS = ["scripted_adversarial", "scripted_benign"]
#: Long enough for each scenario's fault and the agents' answers to it.
CASES = {"OP-03": 1800, "AD-03": 1200, "AD-08": 600}


def card(scenario_id: str) -> dict[str, Any]:
    """Return the card of one scenario, two gates, two agents, seed 1, with replay."""
    profile = load_profile(REPO / "profiles" / "generic_dc.yaml")
    contracts = ContractLibrary.load(REPO / "contracts")
    return run_benchmark(
        profile, contracts, GATES, AGENTS, [scenario_id], [1], CASES[scenario_id],
        counterfactual=True, allow_unfrozen=True,
    )  # fmt: skip


def _text(made: dict[str, Any]) -> str:
    return json.dumps(made, indent=1, sort_keys=True) + "\n"


def _without_oracle(text: str) -> dict[str, Any]:
    made: dict[str, Any] = json.loads(text)
    made["benchmark_version"].pop("oracle")
    return made


@pytest.mark.req("ADC-PLT-001")
@pytest.mark.parametrize("scenario_id", sorted(CASES))
def test_a_card_is_the_same_as_before_the_plant_interface(scenario_id: str) -> None:
    before = (CARDS / f"{scenario_id}.json").read_text(encoding="utf-8")
    now = _text(card(scenario_id))
    assert _without_oracle(now) == _without_oracle(before)
    # Byte for byte too, once the one hash that must differ is put back.
    expected = json.loads(before)
    expected["benchmark_version"]["oracle"] = json.loads(now)["benchmark_version"]["oracle"]
    assert now == _text(expected)


if __name__ == "__main__":
    for name in sys.argv[1:] or sorted(CASES):
        (CARDS / f"{name}.json").write_text(_text(card(name)), encoding="utf-8")
