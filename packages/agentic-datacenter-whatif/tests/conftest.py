from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import Profile, load_profile
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.whatif.models import WhatIfSpec, parse_spec

REPO = Path(__file__).resolve().parents[3]
CHW = "chw.set_supply_setpoint.v1"


@pytest.fixture(scope="session")
def profile() -> Profile:
    return load_profile(REPO / "profiles" / "generic_dc.yaml")


@pytest.fixture(scope="session")
def contracts() -> ContractLibrary:
    return ContractLibrary.load(REPO / "contracts")


@pytest.fixture
def make_spec() -> Callable[..., WhatIfSpec]:
    def make(target: float = 20.5, **overrides: Any) -> WhatIfSpec:
        data: dict[str, Any] = {
            "scenario": "WF-01",
            "seed": 1,
            "duration_s": 3600,
            "change": {
                "contract_id": CHW,
                "argument": "setpoint_c",
                "target": target,
                "expected_start": 18.0,
            },
            "branches": ["baseline", "physical"],
            "policy": {"enabled": False},
        }
        data.update(overrides)
        return parse_spec(data)

    return make


@pytest.fixture
def stand_in_gates() -> dict[str, Callable[[ContractLibrary], Any]]:
    """Gates for the governed branch without REMORA: the null gate stands in.

    The result names the gate that actually decided (``null_gate``), so a run
    made with it can never be mistaken for a governed one.
    """
    return {"remora_governed": lambda _library: NullGate()}
