"""A benchmark made in parts, seed ranges on several machines, merges into the card of the whole."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.null_gate import create as null_gate
from agentic_datacenter.governance.bindings.static_allowlist import create as static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.bench import CardMergeError, merge_cards, run_benchmark

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles/generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
GATES = {"static_allowlist": static_allowlist, "null_gate": null_gate}


def _card(seeds: list[int], **more: object) -> dict[str, object]:
    return run_benchmark(
        PROFILE, CONTRACTS, GATES, ["scripted_adversarial"], ["AD-03"], seeds, 600,
        allow_unfrozen=True, horizon_s=300, **more,  # type: ignore[arg-type]
    )  # fmt: skip


def _text(card: object) -> str:
    return json.dumps(card, indent=2, sort_keys=True)


@pytest.mark.req("ADC-BEN-006")
def test_parts_merge_into_the_card_of_the_whole_byte_for_byte() -> None:
    whole = _card([1, 2])
    assert _text(merge_cards([_card([2]), _card([1])])) == _text(whole)
    assert _text(merge_cards([whole, _card([2])])) == _text(whole)


@pytest.mark.req("ADC-BEN-006")
def test_parts_of_different_benchmarks_are_not_merged() -> None:
    with pytest.raises(CardMergeError, match="judging"):
        merge_cards([_card([1]), _card([2], max_judged=1)])
