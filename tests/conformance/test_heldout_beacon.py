"""Track D secret from a public randomness beacon (preregistration, change of 2026-11-16)."""

from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

REPO = Path(__file__).resolve().parents[2]
# Round 1000 of drand quicknet, as both relays served it.
SIGNATURE = (
    "b44679b9a59af2ec876b1a6b1ad52ea9b1615fc3982b19576350f93447cb1125"
    "e342b73a8dd2bacbe47e4b6b63ed5e39"
)
RANDOMNESS = "fe290beca10872ef2fb164d2aa4442de4566183ec51c56ff3cd603d930e54fdd"


def _tool() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "heldout_beacon", REPO / "tools/heldout_beacon.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _relay(answers: dict[str, dict[str, Any]]) -> Any:
    def fetch(url: str) -> dict[str, Any]:
        return next(a for relay, a in answers.items() if url.startswith(relay))

    return fetch


def test_the_secret_is_the_same_from_every_relay_and_bound_to_the_round() -> None:
    tool = _tool()
    beacon = {"round": 1000, "signature": SIGNATURE, "randomness": RANDOMNESS}
    secret = tool.secret_for(1000, _relay({r: beacon for r in tool.RELAYS}))
    assert secret == f"drand-quicknet:{tool.CHAIN}:1000:{RANDOMNESS}"
    assert hashlib.sha256(bytes.fromhex(SIGNATURE)).hexdigest() == RANDOMNESS


@pytest.mark.parametrize(
    "second",
    [
        {"round": 1000, "signature": SIGNATURE, "randomness": "00" * 32},
        {"round": 1001, "signature": SIGNATURE, "randomness": RANDOMNESS},
    ],
)
def test_a_relay_that_disagrees_or_does_not_derive_its_randomness_is_refused(
    second: dict[str, Any],
) -> None:
    tool = _tool()
    good = {"round": 1000, "signature": SIGNATURE, "randomness": RANDOMNESS}
    first, other = tool.RELAYS
    with pytest.raises(tool.BeaconError):
        tool.secret_for(1000, _relay({first: good, other: second}))


def test_a_round_is_found_from_a_time_and_back() -> None:
    tool = _tool()
    assert tool.round_at(tool.GENESIS) == 1
    number = tool.round_at(1_797_000_000)
    assert tool.emitted_at(number) >= 1_797_000_000 > tool.emitted_at(number - 1)
