"""A gate from another project is checked and benchmarked without changing Agentic-Datacenter.

Covers ``agentic-datacenter gate list|check`` (ADC-GOV-004) and a gate served over HTTP
taken through a benchmark and the release gate (ADC-GOV-008, ADC-BEN-005).
"""

from __future__ import annotations

import importlib.util
import json
import sys
import threading
from collections.abc import Iterator
from http.server import ThreadingHTTPServer
from pathlib import Path

import pytest

from agentic_datacenter.scenarios.cli import bench, gate

REPO = Path(__file__).resolve().parents[2]


def _install(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, points: dict[str, str]) -> None:
    """Install entry points the way a third-party package's metadata would."""
    info = tmp_path / "third_party_gates-0.1.0.dist-info"
    info.mkdir()
    (info / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: third-party-gates\nVersion: 0.1.0\n"
    )
    lines = "".join(f"{name} = {target}\n" for name, target in points.items())
    (info / "entry_points.txt").write_text("[agentic_datacenter.gates]\n" + lines)
    monkeypatch.syspath_prepend(str(tmp_path))


@pytest.fixture
def example_service(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    spec = importlib.util.spec_from_file_location(
        "example_http_gate_server", REPO / "examples/http-gate/server.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    server = ThreadingHTTPServer(("127.0.0.1", 0), module.Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{server.server_address[1]}"
    monkeypatch.setenv("ADC_GATE_URL", url)
    monkeypatch.setenv("ADC_GATE_NAME", "example_service")
    yield url
    server.shutdown()
    server.server_close()


@pytest.mark.req("ADC-GOV-004")
def test_gate_check_passes_a_conforming_gate_and_lists_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "theirs.py").write_text(
        (REPO / "examples/python-gate/src/example_gate/__init__.py").read_text()
    )
    _install(tmp_path, monkeypatch, {"theirs": "theirs:create"})
    sys.modules.pop("theirs", None)
    monkeypatch.chdir(REPO)
    assert gate(["list"]) == 0
    assert "theirs" in capsys.readouterr().out.split()
    assert gate(["check", "theirs"]) == 0
    printed = capsys.readouterr().out
    assert "passed the gate interface suite" in printed and "DECISION_ONLY" in printed


@pytest.mark.req("ADC-GOV-004")
def test_gate_check_names_what_a_gate_gets_wrong(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "broken.py").write_text(
        "from agentic_datacenter.governance.bindings.null_gate import NullGate\n"
        "class NoProfile(NullGate):\n    profile = 'MY_OWN'\n"
        "def create(contracts):\n    return NoProfile()\n"
    )
    _install(tmp_path, monkeypatch, {"broken": "broken:create"})
    sys.modules.pop("broken", None)
    monkeypatch.chdir(REPO)
    assert gate(["check", "broken"]) == 1
    assert "declares profile 'MY_OWN'" in capsys.readouterr().out
    assert gate(["check", "no_such_gate"]) == 2


@pytest.mark.req("ADC-GOV-008")
@pytest.mark.req("ADC-BEN-005")
def test_a_served_gate_is_benchmarked_and_checked_by_the_release_gate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    example_service: str,
) -> None:
    _install(
        tmp_path, monkeypatch, {"served": "agentic_datacenter.governance.bindings.http_gate:create"}
    )
    monkeypatch.chdir(REPO)
    assert gate(["check", "served"]) == 0
    out = tmp_path / "out"
    status = bench(
        [
            "run", "--gate", "served", "--agent", "scripted_adversarial", "--scenario", "AD-03",
            "--seconds", "900", "--allow-unfrozen", "--out", str(out),
        ]
    )  # fmt: skip
    assert status == 0
    card = json.loads((out / "result_card.json").read_text())
    run = next(r for r in card["runs"] if r["gate"] == "served")
    assert run["gate_reported_name"] == "example_service"
    assert card["results"][0]["operating_profile"] == "DECISION_ONLY"
    capsys.readouterr()
    bench(["check", str(out / "result_card.json"), "--gate", "served"])
    assert "served:" in capsys.readouterr().out
