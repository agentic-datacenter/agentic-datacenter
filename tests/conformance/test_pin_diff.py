"""ADC-PIN-004: the metric difference of a pin bump, from the cards of the two pins."""

import copy
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.bindings.static_allowlist import create as static_allowlist
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios.bench import run_benchmark

REPO = Path(__file__).resolve().parents[2]
OLD_PIN = f"tag:         pin-a\ncommit:      {'a' * 40}\n"
NEW_PIN = f"tag:         pin-b\ncommit:      {'b' * 40}\n"


def tool() -> Any:
    spec = importlib.util.spec_from_file_location("pin_diff", REPO / "tools/pin_diff.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def card() -> dict[str, Any]:
    """A real card of one short scenario, as ``bench run`` writes it."""
    made = run_benchmark(
        load_profile(REPO / "profiles/generic_dc.yaml"), ContractLibrary.load(REPO / "contracts"),
        {"static_allowlist": static_allowlist}, ["scripted_adversarial"], ["AD-03"], [1], 600,
        allow_unfrozen=True, horizon_s=300,
    )  # fmt: skip
    return json.loads(json.dumps(made))


def run(tmp_path: Path, old: object, new: object, new_pin: str = NEW_PIN) -> tuple[int, Path]:
    for name, content in (("old.json", old), ("new.json", new)):
        (tmp_path / name).write_text(json.dumps(content))
    (tmp_path / "OLD_PIN").write_text(OLD_PIN)
    (tmp_path / "NEW_PIN").write_text(new_pin)
    out = tmp_path / "pin-diff.md"
    status = tool().main(
        [
            "--old-card", str(tmp_path / "old.json"), "--old-pin", str(tmp_path / "OLD_PIN"),
            "--new-card", str(tmp_path / "new.json"), "--new-pin", str(tmp_path / "NEW_PIN"),
            "--out", str(out),
        ]
    )  # fmt: skip
    return status, out


@pytest.mark.req("ADC-PIN-004")
def test_two_cards_that_agree_give_a_difference_of_nothing(
    tmp_path: Path, card: dict[str, Any]
) -> None:
    status, out = run(tmp_path, card, card)
    page = out.read_text()
    assert status == 0
    assert f"Previous pin: `pin-a`, commit `{'a' * 40}`" in page
    assert f"New pin: `pin-b`, commit `{'b' * 40}`" in page
    assert "Result: no regression." in page
    assert "## Runs that changed: 0 of 1" in page
    assert "| `static_allowlist` | `writes_outside_contract` | 0 | 0 | same |" in page
    figures = [line for line in page.splitlines() if line.startswith("| `safety` ")]
    assert len(figures) == len(card["results"]) and all(f.endswith("| same |") for f in figures)
    assert "development run, not a benchmark result" in page


@pytest.mark.req("ADC-PIN-004")
def test_a_figure_that_moved_is_shown_with_both_values_and_the_change(
    tmp_path: Path, card: dict[str, Any]
) -> None:
    new = copy.deepcopy(card)
    new["results"][0]["false_blocks"] = card["results"][0]["false_blocks"] + 2
    new["runs"][0]["kinds"]["false_block"] = new["runs"][0]["kinds"].get("false_block", 0) + 2
    new["runs"][0]["final_state_hash"] = "0" * 64
    status, out = run(tmp_path, card, new)
    page = out.read_text()
    before = card["results"][0]["false_blocks"]
    assert status == 0, "a figure that is not an invariant does not block the bump"
    assert f"| `false_blocks` | {before} | {before + 2} | +2 |" in page
    assert "## Runs that changed: 1 of 1" in page
    assert f"`{card['runs'][0]['run_id']}`: judgements, final state" in page


@pytest.mark.req("ADC-PIN-004")
@pytest.mark.parametrize("breach", ["writes_outside_contract", "critical_pod_minutes", "harmful"])
def test_more_of_an_invariant_breach_at_the_new_pin_blocks_the_bump(
    tmp_path: Path, card: dict[str, Any], breach: str, capsys: pytest.CaptureFixture[str]
) -> None:
    new = copy.deepcopy(card)
    if breach == "harmful":
        new["runs"][0]["kinds"]["unsafe_execution"] = 1
        breach = "unsafe_execution"
    else:
        new["runs"][0]["metrics"][breach] += 3
    status, out = run(tmp_path, card, new)
    assert status == 1
    assert "Result: BLOCKED." in out.read_text() and f"{breach} rose from" in out.read_text()
    assert f"BLOCKED: static_allowlist: {breach} rose" in capsys.readouterr().err
    # Fewer breaches at the new pin are a change, not a regression.
    assert run(tmp_path, new, card)[0] == 0


@pytest.mark.req("ADC-PIN-004")
def test_cards_of_different_benchmarks_and_equal_pins_are_refused(
    tmp_path: Path, card: dict[str, Any], capsys: pytest.CaptureFixture[str]
) -> None:
    for key, value in (("seeds", [2]), ("judging", {"horizon_s": 1, "max_judged": 1})):
        status, out = run(tmp_path, card, {**card, key: value})
        assert status == 2 and not out.exists()
        assert f"the cards differ in {key}" in capsys.readouterr().err
    fewer = {**card, "runs": []}
    assert run(tmp_path, card, fewer)[0] == 2 and "differ in runs" in capsys.readouterr().err
    assert run(tmp_path, card, card, new_pin=OLD_PIN)[0] == 2
    assert "there is nothing to compare" in capsys.readouterr().err
    assert run(tmp_path, card, card, new_pin="tag: x\n")[0] == 2


@pytest.mark.req("ADC-PIN-004")
def test_every_invariant_of_the_release_gate_is_compared(card: dict[str, Any]) -> None:
    from agentic_datacenter.scenarios.release_gate import BREACHES

    counted = tool().breaches(card, "static_allowlist")
    assert set(BREACHES) < set(counted) and "unsafe_execution" in counted
