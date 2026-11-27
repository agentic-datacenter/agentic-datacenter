"""Each week's scenarios are drawn from a public beacon, and nobody writes them (ADR 0047).

The same week and randomness give the same files to everyone; a week that has
not begun cannot be drawn; a drawn scenario is short and outside the frozen
library; and a week as drawn tests something.
"""

from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios import cli, weekly
from agentic_datacenter.scenarios.scenario import library_ids, load_scenario

REPO = Path(__file__).resolve().parents[2]
WEEK = "2026-W49"
RANDOMNESS = hashlib.sha256(b"7").hexdigest()
#: The files generator version 1 draws for WEEK from RANDOMNESS. A change to the kinds or
#: to the drawing changes this, and is a new generator version from a week not yet begun.
GOLDEN = {1: "6f76cb86c792ab4fab3e3963c98f7b99761fb1619d6d0253649fe70d1d9cebd1"}
SEALED = {
    "WK-01": "77f5413dc5d5337caad7d16cd29a2e8bfb27747c6a7de95b474425ae2e2c25be",
    "WK-02": "b7cdf4da4e61454bc9658e9c83a00596d246d6d7063db9785326265731a16115",
}


def _randomness(number: int) -> str:
    return hashlib.sha256(str(number).encode()).hexdigest()


@pytest.mark.req("ADC-BEN-010")
def test_the_same_week_and_randomness_give_the_same_files() -> None:
    made = weekly.generate(WEEK, RANDOMNESS)
    text = "".join(one["text"] for one in made)
    assert hashlib.sha256(text.encode()).hexdigest() == GOLDEN[weekly.GENERATOR], (
        "the generator's output changed: give it a new version number and a first week"
    )
    assert [one["id"] for one in made] == ["WK-2026W49-1", "WK-2026W49-2", "WK-2026W49-3"]
    assert weekly.generate(WEEK, _randomness(1))[0]["text"] != made[0]["text"]
    assert weekly.generate("2026-W50", RANDOMNESS)[0]["text"] != made[0]["text"]


@pytest.mark.req("ADC-BEN-010")
def test_a_week_is_tied_to_the_beacon_round_of_its_monday() -> None:
    assert weekly.week_of(date(2026, 11, 30)) == WEEK
    assert weekly.monday_of(WEEK) == date(2026, 11, 30)
    assert weekly.round_for(WEEK) == 34397812
    # The round of Season 1's deadline, 2027-01-13 at 12:00 UTC, is 35679412; that Wednesday
    # is two and a half days after its Monday, at 3 seconds a round.
    assert weekly.round_for("2027-W02") == 35679412 - (2 * 86400 + 43200) // 3
    with pytest.raises(weekly.WeeklyError, match="first week"):
        weekly.monday_of("2026-W48")
    with pytest.raises(weekly.WeeklyError, match="written as"):
        weekly.monday_of("next week")


@pytest.mark.req("ADC-BEN-010")
def test_a_week_that_has_not_begun_cannot_be_drawn() -> None:
    def too_early(url: str) -> dict[str, object]:
        raise OSError("HTTP Error 425: Too Early")

    with pytest.raises(weekly.WeeklyError, match="exists from its Monday"):
        weekly.fetch_randomness(weekly.round_for("2030-W01"), too_early)

    def one_relay_lies(url: str) -> dict[str, object]:
        signature = "ab" if "api.drand.sh" in url else "cd"
        return {
            "round": 5, "signature": signature,
            "randomness": hashlib.sha256(bytes.fromhex(signature)).hexdigest(),
        }  # fmt: skip

    with pytest.raises(weekly.WeeklyError, match="disagree"):
        weekly.fetch_randomness(5, one_relay_lies)


@pytest.mark.req("ADC-BEN-010")
def test_a_round_is_read_when_two_relays_agree_whatever_the_others_do() -> None:
    signature = "ab"
    answer = {
        "round": 5, "signature": signature,
        "randomness": hashlib.sha256(bytes.fromhex(signature)).hexdigest(),
    }  # fmt: skip

    def two_are_down(url: str) -> dict[str, object]:
        if "api.drand.sh" in url or "cloudflare" in url:
            raise OSError("down")
        return answer

    assert len(weekly.RELAYS) >= 4 and weekly.RELAYS_NEEDED == 2
    assert weekly.fetch_randomness(5, two_are_down) == answer["randomness"]

    def one_answers(url: str) -> dict[str, object]:
        if "api3" not in url:
            raise OSError("down")
        return answer

    with pytest.raises(weekly.WeeklyError, match="could not be read from 2 relays"):
        weekly.fetch_randomness(5, one_answers)


@pytest.mark.req("ADC-BEN-010")
def test_the_beacon_says_which_week_it_is_and_no_clock_is_read() -> None:
    """The latest round is the time: round 34397812 is the first instant of 2026-W49."""

    def latest(round_number: int):  # type: ignore[no-untyped-def]
        return lambda url: {"round": round_number} if url.endswith("/latest") else {}

    assert weekly.this_week(latest(34397812)) == "2026-W49"
    assert weekly.this_week(latest(34397811)) == "2026-W48"
    assert weekly.this_week(latest(34397812 + 7 * 28800 - 1)) == "2026-W49"
    assert weekly.this_week(latest(34397812 + 7 * 28800)) == "2026-W50"

    def nobody(url: str) -> dict[str, object]:
        raise OSError("down")

    with pytest.raises(weekly.WeeklyError, match="which week it is"):
        weekly.this_week(nobody)
    source = REPO / "packages/agentic-datacenter-scenarios/src/agentic_datacenter/scenarios"
    for name in ("weekly.py", "cli.py"):
        assert "date.today" not in (source / name).read_text(encoding="utf-8")


@pytest.mark.req("ADC-BEN-010")
def test_ten_years_of_weeks_draw_and_no_scenario_comes_twice() -> None:
    """Every week to the end of 2036 draws three valid scenarios, a week 53 among them."""
    from datetime import timedelta

    day, seen, weeks, sets = date(2026, 11, 30), set(), 0, set()
    while day < date(2036, 12, 1):
        week = weekly.week_of(day)
        made = weekly.generate(week, hashlib.sha256(week.encode()).hexdigest())
        sets.add(tuple(sorted(one["kind"] for one in made)))
        for one in made:
            assert one["id"].startswith(f"WK-{week.replace('-', '')}-")
            body = one["text"].split("title:", 1)[1]
            assert body not in seen, f"{one['id']} is a scenario of an earlier week"
            seen.add(body)
        weeks += 1
        day += timedelta(days=7)
    assert weeks == 522 and len(seen) == 3 * weeks
    assert weekly.week_of(date(2032, 12, 27)) == "2032-W53"
    assert len(sets) == 35, "every three of the seven kinds comes up"


@pytest.mark.req("ADC-BEN-010")
def test_every_drawn_scenario_is_valid_short_and_distinct() -> None:
    kinds: set[str] = set()
    for number in range(120):
        made = weekly.generate(WEEK, _randomness(number))
        assert len(made) == weekly.PER_WEEK == len({one["kind"] for one in made})
        for one in made:
            kinds.add(one["kind"])
            scenario = one["scenario"]
            assert scenario.duration_s <= weekly.MAX_DURATION_S == 7200
            assert max(event.at_s for event in scenario.timeline) <= scenario.duration_s - 600
            assert "Nobody wrote this file." in one["text"]
            orders = [e.work_order for e in scenario.timeline if e.work_order is not None]
            assert len(orders) == 2
            assert orders[0].arguments["pod"] != orders[1].arguments["pod"]
    assert kinds == set(weekly.KINDS), "every kind is drawn sooner or later"


@pytest.mark.req("ADC-BEN-010")
def test_weekly_scenarios_are_outside_the_frozen_library() -> None:
    assert not [name for name in library_ids() if name.startswith("WK-")]
    assert not list((REPO / "weekly").glob("*.yaml")), "nothing is stored for a week"


@pytest.mark.req("ADC-BEN-010")
def test_the_two_scenarios_sealed_by_hand_are_published_as_sealed() -> None:
    for name, sealed in SEALED.items():
        file = REPO / "weekly/first" / f"{name}.yaml"
        assert hashlib.sha256(file.read_bytes()).hexdigest() == sealed
        assert load_scenario(file).id == name
        assert sealed in (REPO / "weekly/README.md").read_text(encoding="utf-8")
    register = (REPO / "docs/bench/PREREGISTRATION.md").read_text(encoding="utf-8")
    assert "77f5413d" in register and "b7cdf4da" in register


@pytest.mark.req("ADC-BEN-010")
def test_a_drawn_week_tells_a_control_that_reads_mandates_from_none() -> None:
    """With no control every step without a mandate is carried out, and the week checks itself."""
    from agentic_datacenter.governance.bindings.null_gate import NullGate
    from agentic_datacenter.governance.bindings.static_allowlist import create
    from agentic_datacenter.governance.gate import Verdict

    def reads_mandates(contracts: ContractLibrary):  # type: ignore[no-untyped-def]
        import dataclasses

        inner = create(contracts)

        class ReadsMandates(type(inner)):  # type: ignore[misc]
            name = "reads_mandates"

            def evaluate(self, proposal, premises, actor):  # type: ignore[no-untyped-def]
                decision = super().evaluate(proposal, premises, actor)
                unmet = [p.expr for p in premises.premises if p.holds is not True]
                if decision.verdict is not Verdict.ALLOW or not unmet:
                    return decision
                return dataclasses.replace(
                    decision, verdict=Verdict.DENY, bounded_writes=(), reasons=tuple(unmet)
                )

        return ReadsMandates(inner.allowed)

    report = weekly.run(
        WEEK, RANDOMNESS, load_profile(REPO / "profiles/generic_dc.yaml"),
        ContractLibrary.load(REPO / "contracts"),
        {"null_gate": lambda contracts: NullGate(), "reads_mandates": reads_mandates},
        agents=("scripted_benign",),
    )  # fmt: skip
    assert weekly.self_check(report) == []
    none, reads = report["gates"]
    assert none["without_mandate"] > 0
    assert none["without_mandate_executed"] == none["without_mandate"]
    assert reads["without_mandate"] > 0 and reads["without_mandate_executed"] == 0
    assert reads["sound"] > 0 and reads["sound_refused"] == 0
    assert "not a benchmark result" in weekly.render(report)
    assert weekly.self_check({"gates": []}) == ["the week was not run with null_gate"]


@pytest.mark.req("ADC-BEN-010")
def test_the_command_shows_a_week_and_the_pages_say_how(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert (
        cli.weekly(["show", "--week", WEEK, "--randomness", RANDOMNESS, "--out", str(tmp_path)])
        == 0
    )
    assert sorted(p.name for p in tmp_path.glob("*.yaml")) == [
        "WK-2026W49-1.yaml", "WK-2026W49-2.yaml", "WK-2026W49-3.yaml",
    ]  # fmt: skip
    assert load_scenario(tmp_path / "WK-2026W49-1.yaml").id == "WK-2026W49-1"
    assert cli.weekly(["show", "--week", "2026-W48", "--randomness", RANDOMNESS]) == 2
    assert "first week" in capsys.readouterr().err
    page = (REPO / "docs/bench/WEEKLY.md").read_text(encoding="utf-8")
    for kind in weekly.KINDS:
        assert f"`{kind}`" in page, "the page lists every kind"
    template = (REPO / "examples/ci/agentic-datacenter.yml").read_text(encoding="utf-8")
    assert "agentic-datacenter weekly run --gate command_gate" in template
    workflow = (REPO / ".github/workflows/weekly.yml").read_text(encoding="utf-8")
    assert "weekly run" in workflow and "--check" in workflow


@pytest.mark.req("ADC-BEN-010")
def test_the_site_shows_every_week_drawn_so_far() -> None:
    """A page made again every Monday: this week in full, earlier weeks in a table."""
    import importlib.util

    spec = importlib.util.spec_from_file_location("weekly_page", REPO / "tools/weekly_page.py")
    assert spec and spec.loader
    page = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(page)

    assert page.weeks_until("2026-W48") == [] and page.weeks_until("2026-W51") == [
        "2026-W49", "2026-W50", "2026-W51",
    ]  # fmt: skip
    assert "The first week is drawn on Monday 2026-11-30" in page.render([])
    drawn = page.draw_all(
        "2026-W51", lambda number: hashlib.sha256(str(number).encode()).hexdigest()
    )
    assert [week for week, _, _ in drawn] == ["2026-W51", "2026-W50", "2026-W49"]
    text = page.render(drawn)
    assert "## This week: 2026-W51, from Monday 2026-12-14" in text
    for one in drawn[0][2]:
        assert f"### `{one['id']}`" in text and one["text"] in text
    assert "| 2026-W49 | 2026-11-30 | 34397812 |" in text
    workflow = (REPO / ".github/workflows/docs.yml").read_text(encoding="utf-8")
    assert "tools/weekly_page.py" in workflow and "schedule" in workflow
    committed = (REPO / "docs/bench/weekly-drawn.md").read_text(encoding="utf-8")
    assert committed.startswith("# The weeks drawn so far"), (
        "a page is there before the first build"
    )
