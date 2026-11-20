"""The `agentic-datacenter modules` commands."""

from importlib.metadata import entry_points
from pathlib import Path

import pytest

from agentic_datacenter.core.cli import main

REPO = Path(__file__).resolve().parents[2]


def test_list_prints_one_line_per_module(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["modules", "list"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 16
    assert any(line.startswith("electrical.power_train") and " F1 " in line for line in lines)


def test_graph_prints_the_ports_of_each_module(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["modules", "graph"]) == 0
    out = capsys.readouterr().out
    assert "electrical.mv_switchgear\n  provides  feeder[trains]:electrical" in out
    assert "  requires  gen_ready_to_load:signal" in out


@pytest.mark.req("ADC-MOD-005")
def test_lock_check_accepts_the_committed_file() -> None:
    assert main(["modules", "lock", "--check", "--path", str(REPO / "modules.lock.yaml")]) == 0


@pytest.mark.req("ADC-MOD-005")
def test_lock_check_rejects_a_stale_or_missing_file(tmp_path: Path) -> None:
    stale = tmp_path / "modules.lock.yaml"
    assert main(["modules", "lock", "--check", "--path", str(stale)]) == 1
    stale.write_text("modules: []\n", encoding="utf-8")
    assert main(["modules", "lock", "--check", "--path", str(stale)]) == 1


def test_lock_writes_a_file_that_then_passes_the_check(tmp_path: Path) -> None:
    path = tmp_path / "modules.lock.yaml"
    assert main(["modules", "lock", "--path", str(path)]) == 0
    assert main(["modules", "lock", "--check", "--path", str(path)]) == 0


GENERIC = str(REPO / "profiles/generic_dc.yaml")


def test_profile_validate_accepts_the_generic_profile(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["profile", "validate", GENERIC]) == 0
    assert "generic_dc" in capsys.readouterr().out


def test_profile_validate_rejects_a_bad_file(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: 1\nname: bad\n", encoding="utf-8")
    assert main(["profile", "validate", str(bad)]) == 1
    assert "site" in capsys.readouterr().err


def test_profile_schema_check_accepts_the_committed_schema() -> None:
    assert main(["profile", "schema", "--check", "--path", str(REPO / "profiles/schema.json")]) == 0


def test_graph_with_a_profile_prints_the_wiring(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["modules", "graph", "--profile", GENERIC]) == 0
    out = capsys.readouterr().out
    assert "electrical.ups[A].input  <-  electrical.power_train[A].lv_bus  (electrical)" in out
    assert out.count("<-") == 171


def test_run_prints_the_same_final_hash_for_the_same_seed(
    capsys: pytest.CaptureFixture[str],
) -> None:
    args = ["run", "--profile", GENERIC, "--seed", "7", "--seconds", "5"]
    assert main(args) == 0
    first = capsys.readouterr().out
    assert main(args) == 0
    second = capsys.readouterr().out
    hash_line = [line for line in first.splitlines() if line.startswith("state hash")]
    assert hash_line and hash_line == [
        line for line in second.splitlines() if line.startswith("state hash")
    ]
    assert "simulated time  5.0 s" in first


def test_help_lists_every_command_with_a_description(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        main(["--help"])
    assert stopped.value.code == 0
    out = capsys.readouterr().out
    added = sorted(point.name for point in entry_points(group="agentic_datacenter.commands"))
    assert {"bench", "gate", "demo", "scenario", "whatif"} <= set(added)
    for name in ["modules", "profile", "run", *added]:
        line = next((line for line in out.splitlines() if line.split()[:1] == [name]), "")
        assert len(line.split()) > 1, f"{name} has no description in --help"
