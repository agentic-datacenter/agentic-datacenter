"""REMORA's policy analysis of the change: advisory, separate, and absent without REMORA."""

import json
import sys
from collections.abc import Callable
from typing import Any

import pytest

from agentic_datacenter.core.profile import Profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.whatif.models import WhatIfSpec
from agentic_datacenter.whatif.policy import RECONFIGURATION, _plain, run_policy

FORBIDDEN = ("execution_token", "execution_grant", "decision_ref", "lease", "approved_by")


def has_analysis() -> bool:
    try:
        from agentic_datacenter_remora import whatif
    except ImportError:
        return False
    return whatif.unavailable_reason() is None


@pytest.mark.req("ADC-WIF-004")
def test_without_the_remora_binding_the_policy_part_is_skipped_and_says_so(
    make_spec: Callable[..., WhatIfSpec],
    profile: Profile,
    contracts: ContractLibrary,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # As if the binding were not installed: importing it fails.
    monkeypatch.setitem(sys.modules, "agentic_datacenter_remora", None)
    monkeypatch.setitem(sys.modules, "agentic_datacenter_remora.whatif", None)
    result = run_policy(make_spec(20.5, policy={"enabled": True}), profile, contracts)
    assert result["available"] is False
    assert "REMORA" in result["reason"] and result["calls"] == []
    assert result["grants"] == "nothing"


def test_a_request_that_turns_the_analysis_off_is_labelled_as_such(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    result = run_policy(make_spec(20.5), profile, contracts)
    assert result["available"] is False and "not requested" in result["reason"]


@pytest.mark.req("ADC-WIF-004")
@pytest.mark.skipif(not has_analysis(), reason="needs a REMORA with remora.sdk.what_if")
def test_the_analysis_names_the_guard_on_the_one_call_and_grants_nothing(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    result = run_policy(make_spec(20.5, policy={"enabled": True}), profile, contracts)
    assert result["available"] is True and result["grants"] == "nothing"
    calls = {call["call"]: call for call in result["calls"]}
    assert set(calls) == {"as_one_call", "first_step"}
    assert calls["as_one_call"]["arguments"] == {"setpoint_c": 20.5}
    assert calls["first_step"]["arguments"] == {"setpoint_c": 18.5}
    one = {stage["stage"]: stage for stage in calls["as_one_call"]["stages"]}
    assert one["pure_decision"]["report"]["current_action"] != "accept"
    assert one["pure_decision"]["report"]["hard_guard"] == "malformed_call_blocked"
    first = {stage["stage"]: stage for stage in calls["first_step"]["stages"]}
    service = first["execution_service"]
    assert service["report"]["current_action"] == "accept"
    assert service["report"]["current_reasons"] == ["bounded_write_accept"]
    assert service["engine"]["bounded_write_accept"] is True
    assert service["engine"]["execution_profile"] is True
    text = json.dumps(result)
    for word in FORBIDDEN:
        assert word not in text


@pytest.mark.req("ADC-WIF-004")
@pytest.mark.skipif(not has_analysis(), reason="needs a REMORA with remora.sdk.what_if")
def test_a_deployment_fact_is_never_offered_as_an_option(
    make_spec: Callable[..., WhatIfSpec], profile: Profile, contracts: ContractLibrary
) -> None:
    result = run_policy(make_spec(20.5, policy={"enabled": True}), profile, contracts)
    seen: list[dict[str, Any]] = []
    for call in result["calls"]:
        for stage in call["stages"]:
            seen += stage["levers"]
    assert seen, "the one call has levers that move its verdict"
    for lever in seen:
        if lever["kind"] == "deployment_fact":
            assert lever["who"] == RECONFIGURATION
        else:
            assert lever["who"] != RECONFIGURATION


def stage_of(exhausted: bool, **report: Any) -> dict[str, Any]:
    return {
        "stage": "pure_decision",
        "report": {
            "current_action": "escalate", "target": "accept", "minimal_paths": [],
            "without_deployment": None, "search": {"exhausted": exhausted}, **report,
        },
    }  # fmt: skip


DEPLOYMENT_PATH = {"levers": ["risk_tier_low"], "kinds": ["deployment_fact"]}
AGENT_PATH = {"levers": ["schema_valid", "trust_high"], "kinds": ["model_signal", "proposal"]}


@pytest.mark.req("ADC-WIF-004")
def test_the_sentence_says_unknown_when_the_budget_stopped_the_search() -> None:
    assert "no change set within the search bound" in _plain("c", stage_of(True))
    nothing = _plain("c", stage_of(False))
    assert "unknown" in nothing and "no change set within" not in nothing
    proved = _plain("c", stage_of(True, minimal_paths=[DEPLOYMENT_PATH]))
    assert "every path to ACCEPT needs a deployment fact" in proved
    unproved = _plain("c", stage_of(False, minimal_paths=[DEPLOYMENT_PATH]))
    assert "unknown" in unproved and "every path" not in unproved
    assert RECONFIGURATION in unproved


@pytest.mark.req("ADC-WIF-004")
def test_a_larger_path_of_the_agents_own_is_not_hidden_by_a_smaller_deployment_path() -> None:
    stage = stage_of(True, minimal_paths=[DEPLOYMENT_PATH], without_deployment=AGENT_PATH)
    text = _plain("c", stage)
    assert "a different proposal would reach ACCEPT (schema_valid + trust_high)" in text
    assert "every path" not in text


@pytest.mark.req("ADC-WIF-004")
def test_a_path_found_before_the_budget_ran_out_is_reported_with_what_is_not_known() -> None:
    # The agent's search found it; the search over all levers was stopped with nothing.
    text = _plain("c", stage_of(False, without_deployment=AGENT_PATH))
    assert "a different proposal would reach ACCEPT" in text
    assert "stopped by its evaluation budget" in text and "before a change set" not in text
    model = {"levers": ["trust_high"], "kinds": ["model_signal"]}
    text = _plain("c", stage_of(False, model_signals_alone=model))
    assert "model signals alone would reach ACCEPT (trust_high)" in text


@pytest.mark.req("ADC-WIF-004")
def test_a_report_that_does_not_say_its_search_finished_is_read_as_unfinished() -> None:
    stage = stage_of(True)
    del stage["report"]["search"]
    assert "unknown" in _plain("c", stage)
