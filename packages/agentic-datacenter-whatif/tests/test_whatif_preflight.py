"""The contract preflight: does the change fit chw.set_supply_setpoint.v1 at the start state?"""

from collections.abc import Callable
from typing import Any

import pytest

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.whatif.models import SpecError, WhatIfSpec
from agentic_datacenter.whatif.preflight import run_preflight


def checks(result: dict[str, Any]) -> dict[str, bool]:
    return {c["name"]: c["passed"] for c in result["checks"]}


@pytest.mark.req("ADC-WIF-004")
def test_20_5_from_18_is_inside_the_bounds_but_too_big_a_step_and_over_the_day(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    result = run_preflight(make_spec(20.5), profile, contracts)
    assert result["start_value"] == 18.0 and result["target"] == 20.5
    assert result["delta"] == pytest.approx(2.5)
    assert checks(result) == {
        "range": True,
        "step": False,
        "rate": True,
        "cumulative": False,
        "premises": True,
    }
    assert result["steps_needed"] == 5 and result["max_step"] == 0.5
    assert result["cumulative_limit"] == 2.0 and result["window_h"] == 24.0
    assert result["max_reachable_in_window"] == pytest.approx(20.0)
    assert result["reachable_within_window"] is False
    assert result["verdict"] == "not_reachable_within_window"
    step = next(c for c in result["checks"] if c["name"] == "step")
    assert "2.5" in step["detail"] and "0.5" in step["detail"]


@pytest.mark.req("ADC-WIF-004")
def test_19_5_takes_three_steps_and_fits_the_day(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    result = run_preflight(make_spec(19.5), profile, contracts)
    assert checks(result)["step"] is False and checks(result)["cumulative"] is True
    assert result["steps_needed"] == 3 and result["reachable_within_window"] is True
    assert result["verdict"] == "reachable_in_steps"
    # Two steps an hour: the third can come one hour after the first.
    assert result["earliest_last_step_h"] == pytest.approx(1.0)


def test_half_a_kelvin_fits_as_one_call(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    result = run_preflight(make_spec(18.5), profile, contracts)
    assert all(checks(result).values()) and result["verdict"] == "fits_as_one_call"


def test_a_target_outside_the_contract_range_is_named(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    result = run_preflight(make_spec(22.0), profile, contracts)
    assert checks(result)["range"] is False and result["verdict"] == "outside_bounds"


def test_premises_are_read_at_the_start_state_and_listed(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    result = run_preflight(make_spec(20.5), profile, contracts)
    exprs = [p["expr"] for p in result["premises"]]
    assert "tes.charge_pct >= 80" in exprs and "redundancy.chillers >= N_PLUS_1" in exprs
    assert all(p["holds"] is True for p in result["premises"])
    assert len(result["start_state_hash"]) == 64


def test_the_preflight_grants_nothing(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    result = run_preflight(make_spec(20.5), profile, contracts)
    assert result["grants"] == "nothing"
    text = repr(result)
    assert "decision_ref" not in text and "token" not in text


def test_a_start_that_differs_from_the_expected_one_is_refused(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    spec = make_spec(20.5, change={
        "contract_id": "chw.set_supply_setpoint.v1", "argument": "setpoint_c",
        "target": 20.5, "expected_start": 19.0,
    })  # fmt: skip
    with pytest.raises(SpecError, match="18"):
        run_preflight(spec, profile, contracts)


def test_a_contract_that_cannot_be_studied_is_refused(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    unknown = make_spec(change={"contract_id": "no.such.v1", "argument": "x", "target": 1.0})
    with pytest.raises(SpecError, match="no.such.v1"):
        run_preflight(unknown, profile, contracts)
    rotate = make_spec(change={
        "contract_id": "chw.rotate_lead_chiller.v1", "argument": "lead", "target": 2.0,
    })  # fmt: skip
    with pytest.raises(SpecError, match="number"):
        run_preflight(rotate, profile, contracts)
