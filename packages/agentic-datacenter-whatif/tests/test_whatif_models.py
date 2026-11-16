"""Request validation (ADR 0019) and the WF-nn scenario ids (SDD 10.4)."""

from typing import Any

import pytest

from agentic_datacenter.scenarios.scenario import ScenarioError, parse_scenario
from agentic_datacenter.whatif.models import SpecError, load_whatif_scenario, parse_spec

GOOD: dict[str, Any] = {
    "scenario": "WF-01",
    "change": {
        "contract_id": "chw.set_supply_setpoint.v1",
        "argument": "setpoint_c",
        "target": 20.5,
    },
}


def test_a_minimal_request_takes_the_defaults() -> None:
    spec = parse_spec(GOOD)
    assert spec.schema_version == 1 and spec.seed == 1 and spec.duration_s is None
    assert spec.branches == ("baseline", "physical", "governed")
    assert spec.energy_price is None, "no default price is ever invented"
    assert spec.policy.enabled and spec.policy.max_depth >= 1


def test_the_request_hash_is_stable_and_changes_with_the_request() -> None:
    assert parse_spec(GOOD).hash() == parse_spec(dict(GOOD)).hash()
    other = {**GOOD, "seed": 2}
    assert parse_spec(other).hash() != parse_spec(GOOD).hash()


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"seed": -1}, "seed"),
        ({"duration_s": 0}, "duration_s"),
        ({"scenario": "OP-10"}, "scenario"),
        ({"scenario": "../etc/passwd"}, "scenario"),
        ({"branches": ["physical"]}, "baseline"),
        ({"branches": ["baseline", "baseline"]}, "twice"),
        ({"branches": ["baseline", "shadow"]}, "branches"),
        ({"surprise": True}, "surprise"),
        ({"change": {**GOOD["change"], "target": "warm"}}, "target"),
        ({"change": {**GOOD["change"], "target": float("nan")}}, "target"),
        ({"energy_price": {"per_kwh": 0.0, "currency": "NOK"}}, "per_kwh"),
        ({"energy_price": {"per_kwh": 1.2, "currency": "kroner"}}, "currency"),
        ({"policy": {"max_depth": 0}}, "max_depth"),
    ],
)
def test_invalid_requests_are_refused_with_the_field_named(
    change: dict[str, Any], message: str
) -> None:
    with pytest.raises(SpecError, match=message):
        parse_spec({**GOOD, **change})


def test_a_request_must_be_a_mapping() -> None:
    with pytest.raises(SpecError):
        parse_spec(["WF-01"])


def test_a_price_is_carried_with_its_currency() -> None:
    spec = parse_spec({**GOOD, "energy_price": {"per_kwh": 1.25, "currency": "NOK"}})
    assert spec.energy_price is not None
    assert (spec.energy_price.per_kwh, spec.energy_price.currency) == (1.25, "NOK")


def test_the_scenario_schema_takes_wf_ids_besides_op_and_ad() -> None:
    base = {"schema_version": 1, "title": "x", "track": "B", "duration_s": 60}
    assert parse_scenario({**base, "id": "WF-07"}).id == "WF-07"
    assert parse_scenario({**base, "id": "OP-01"}).id == "OP-01"
    with pytest.raises(ScenarioError):
        parse_scenario({**base, "id": "XX-01"})


def test_wf01_is_normal_operation_at_20_degrees_for_a_day() -> None:
    scenario = load_whatif_scenario("WF-01")
    assert scenario.id == "WF-01" and scenario.duration_s == 86400
    assert scenario.decision_every_s == 900 and scenario.objective == "energy"
    [event] = scenario.timeline
    assert event.module == "cooling.weather[SITE]" and event.inject == "set"
    assert event.params == {"dry_bulb_c": 20.0}


def test_an_unknown_what_if_scenario_is_refused() -> None:
    with pytest.raises(SpecError, match="WF-99"):
        load_whatif_scenario("WF-99")
