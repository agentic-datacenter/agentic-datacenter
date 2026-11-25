"""A language-model agent, optional and apart from the scripted agents (ADR 0035).

No test here calls a model or needs a network: the model is a scripted fake
transport, and the SDKs are stood in for where their use is tested.
"""

from __future__ import annotations

import json
import sys
import types
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from agentic_datacenter.core.profile import load_profile
from agentic_datacenter.governance.agent_tools.server import TOOLS
from agentic_datacenter.governance.bindings import static_allowlist
from agentic_datacenter.governance.bindings.null_gate import NullGate
from agentic_datacenter.governance.contracts import ContractLibrary
from agentic_datacenter.scenarios import llm_providers
from agentic_datacenter.scenarios.agents import AGENTS, CHW_CONTRACT, CHWS
from agentic_datacenter.scenarios.bench import benchmark_version, render_report, run_benchmark
from agentic_datacenter.scenarios.cli import agent as agent_cli
from agentic_datacenter.scenarios.cli import bench as bench_cli
from agentic_datacenter.scenarios.cli import scenario as scenario_cli
from agentic_datacenter.scenarios.evidence import verify_bundle
from agentic_datacenter.scenarios.harness import run_scenario
from agentic_datacenter.scenarios.llm_agent import (
    LLM_LABEL,
    PROVIDERS,
    SCRIPTED_NOTE,
    TOOL_SPECS,
    LlmAgent,
    LlmAgentError,
    LlmOptions,
    Recorder,
    Replayer,
    agent_kind,
    call_tool,
    parse_name,
)
from agentic_datacenter.scenarios.release_gate import check_card
from agentic_datacenter.scenarios.scenario import load_scenario

REPO = Path(__file__).resolve().parents[2]
PROFILE = load_profile(REPO / "profiles" / "generic_dc.yaml")
CONTRACTS = ContractLibrary.load(REPO / "contracts")
MODEL = "llm:anthropic/claude-opus-5-5"
#: Two decision points of OP-03, at 300 s and 600 s.
SECONDS = 900


def _reply(text: str = "", calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "text": text, "tool_calls": calls or [], "stop": "tool_use" if calls else "end_turn",
        "model": "claude-opus-5-5", "usage": {"input_tokens": 100, "output_tokens": 10},
    }  # fmt: skip


def fake_model(request: Mapping[str, Any]) -> dict[str, Any]:
    """At the first decision point read the setpoint, then raise it half a kelvin; then stop."""
    history = request["history"]
    shown = json.loads(history[0]["text"].split("\n", 1)[1])
    if shown["time_s"] != 300:
        return _reply("The plant is steady; nothing to do.")
    rounds = sum(1 for turn in history if turn["role"] == "assistant")
    if rounds == 0:
        return _reply(calls=[{"id": "c1", "name": "get_points", "arguments": {"tags": [CHWS]}}])
    if rounds == 1:
        value = json.loads(history[-1]["results"][0]["content"])[0]["value"]
        return _reply(calls=[{
            "id": "c2", "name": "propose_action",
            "arguments": {"contract_id": CHW_CONTRACT, "arguments": {"setpoint_c": value + 0.5},
                          "rationale": "the plant is healthy; save chiller energy"},
        }])  # fmt: skip
    return _reply("Proposed one step.")


def _run(agent: LlmAgent, gate: Any = None) -> Any:
    gate = gate or NullGate()
    operating = str(getattr(gate, "profile", "UNGOVERNED"))
    return run_scenario(
        load_scenario("OP-03"), PROFILE, gate, operating, agent, 1, CONTRACTS, SECONDS
    )


@pytest.mark.req("ADC-AGT-001")
def test_the_scripted_agents_are_the_default_and_a_model_is_named_to_be_used() -> None:
    assert agent_kind(sorted(AGENTS)) == "scripted"
    assert agent_kind([MODEL]) == "language_model"
    assert parse_name("llm:openai/gpt-5.1") == ("openai", "gpt-5.1")
    assert set(PROVIDERS) == {"anthropic", "openai", "gemini", "xai", "compatible"}
    for wrong in ("llm:nobody/x", "llm:openai/", "gpt-5", "llm:anthropic"):
        with pytest.raises(LlmAgentError):
            parse_name(wrong)
    # A card of scripted agents is the card it was: no field of the new agent on it.
    card = run_benchmark(
        PROFILE, CONTRACTS, {"null_gate": lambda c: NullGate()}, ["scripted_benign"], ["OP-03"],
        [1], 600, counterfactual=False, allow_unfrozen=True,
    )  # fmt: skip
    assert "agent_kind" not in card and "language_models" not in card
    assert SCRIPTED_NOTE in render_report(card)


@pytest.mark.req("ADC-AGT-001")
def test_the_module_is_outside_the_benchmark_version() -> None:
    frozen = json.loads((REPO / "docs/bench/VERSION.json").read_text(encoding="utf-8"))
    version = benchmark_version(PROFILE, CONTRACTS, frozen["scenarios"])
    assert version["agents"] == frozen["version"]["agents"]


@pytest.mark.req("ADC-AGT-003")
def test_the_model_is_given_the_tools_of_an_agent_and_nothing_else() -> None:
    assert {spec["name"] for spec in TOOL_SPECS} == set(TOOLS)
    propose = next(s for s in TOOL_SPECS if s["name"] == "propose_action")
    assert set(propose["parameters"]["properties"]) == {"contract_id", "arguments", "rationale"}


@pytest.mark.req("ADC-AGT-003")
def test_every_proposal_of_the_model_goes_through_the_gate() -> None:
    agent = LlmAgent("anthropic", "claude-opus-5-5", fake_model)
    result = _run(agent, static_allowlist.create(CONTRACTS))
    assert result.agent == MODEL
    mine = [r for r in result.records if r["contract_id"] == CHW_CONTRACT]
    assert len(mine) == 1 and mine[0]["verdict"] in ("ALLOW", "DENY", "VERIFY", "ABSTAIN")
    assert agent.usage.proposals == 1 and agent.usage.calls == 4


@pytest.mark.req("ADC-AGT-003")
def test_a_tool_the_model_invents_or_misuses_is_answered_with_an_error() -> None:
    calls: list[dict[str, Any]] = []

    def model(request: Mapping[str, Any]) -> dict[str, Any]:
        if request["history"][-1]["role"] == "tool":
            calls.extend(request["history"][-1]["results"])
            return _reply("done")
        return _reply(calls=[
            {"id": "a", "name": "write_point", "arguments": {"tag": CHWS, "value": 25}},
            {"id": "b", "name": "get_points", "arguments": {"tags": "not a list"}},
            {"id": "c", "name": "propose_action", "arguments": "{not json"},
        ])  # fmt: skip

    result = _run(LlmAgent("openai", "m", model))
    assert not [r for r in result.records if r["principal"] != "operator"]
    assert calls and all(c["error"] for c in calls[:3])
    assert "no such tool" in calls[0]["content"]


@pytest.mark.req("ADC-AGT-003")
def test_call_tool_offers_no_claimed_actor() -> None:
    class Tools:
        def propose_action(self, contract_id: str, arguments: Any, rationale: str = "",
                           claimed_actor: str | None = None) -> dict[str, Any]:  # fmt: skip
            return {"claimed_actor": claimed_actor}

    out, failed = call_tool(
        Tools(),  # type: ignore[arg-type]
        "propose_action",
        {"contract_id": "x", "arguments": {}, "rationale": "", "claimed_actor": "operator"},
    )
    assert not failed and out == {"claimed_actor": None}


@pytest.mark.req("ADC-AGT-005")
def test_a_run_replayed_from_its_transcript_is_the_same_run(tmp_path: Path) -> None:
    path = tmp_path / "run.jsonl"
    live = _run(LlmAgent("anthropic", "claude-opus-5-5", Recorder(fake_model, path)))
    lines = [json.loads(t) for t in path.read_text(encoding="utf-8").splitlines()]
    assert len(lines) == 4 and all(line["reply"]["model"] == "claude-opus-5-5" for line in lines)
    assert all(line["request"]["model"] == "claude-opus-5-5" for line in lines)
    again = _run(LlmAgent("anthropic", "claude-opus-5-5", Replayer(path)))
    assert again.records == live.records and again.state_hashes == live.state_hashes
    with pytest.raises(LlmAgentError, match="not the one recorded"):
        _run(LlmAgent("anthropic", "another-model", Replayer(path)))


@pytest.mark.req("ADC-AGT-007")
def test_the_agent_stops_calling_the_model_when_its_budget_is_spent() -> None:
    agent = LlmAgent("anthropic", "claude-opus-5-5", fake_model, max_calls=1)
    _run(agent)
    assert agent.usage.calls == 1 and agent.usage.budget_exhausted


@pytest.mark.req("ADC-AGT-007")
def test_a_refusal_ends_the_decision_and_is_counted() -> None:
    agent = LlmAgent("anthropic", "claude-opus-5-5", lambda r: {**_reply(), "stop": "refusal"})
    _run(agent)
    assert agent.usage.refusals == agent.usage.calls == 2 and agent.usage.proposals == 0


def _live_fake(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(llm_providers, "live_transport", lambda provider: fake_model)


@pytest.mark.req("ADC-AGT-004")
@pytest.mark.req("ADC-AGT-002")
def test_a_card_of_a_model_is_apart_labelled_and_refused_for_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _live_fake(monkeypatch)
    gates = {"null_gate": lambda c: NullGate()}
    with pytest.raises(LlmAgentError, match="never beside them"):
        run_benchmark(PROFILE, CONTRACTS, gates, ["scripted_benign", MODEL], ["OP-03"], [1],
                      SECONDS, allow_unfrozen=True)  # fmt: skip
    options = LlmOptions(transcripts=tmp_path / "t")
    card = run_benchmark(
        PROFILE, CONTRACTS, gates, [MODEL], ["OP-03"], [1], SECONDS, allow_unfrozen=True,
        llm=options,
    )  # fmt: skip
    assert card["label"] == LLM_LABEL and card["agent_kind"] == "language_model"
    assert card["counterfactual"] is False
    assert card["language_models"] == [
        {"provider": "anthropic", "model": "claude-opus-5-5", "mode": "live"}
    ]
    used = card["results"][0]["agent_usage"]
    assert used["calls"] == 4 and used["proposals"] == 1
    run = card["runs"][0]
    assert run["agent_kind"] == "language_model" and run["agent_usage"]["transcript_sha256"]
    page = render_report(card)
    assert "Language-model agent: anthropic/claude-opus-5-5" in page and SCRIPTED_NOTE not in page
    report = check_card(card, "null_gate", publication=True)
    assert any("language-model agent" in v for v in report.violations)
    # Replayed from the transcripts, with no model, the runs are the runs.
    monkeypatch.setattr(llm_providers, "live_transport", None)
    again = run_benchmark(
        PROFILE, CONTRACTS, gates, [MODEL], ["OP-03"], [1], SECONDS, allow_unfrozen=True,
        llm=LlmOptions(replay=tmp_path / "t"),
    )  # fmt: skip
    assert again["language_models"][0]["mode"] == "replay"
    assert again["runs"] == card["runs"]


@pytest.mark.req("ADC-AGT-002")
def test_the_evidence_bundle_says_which_agent_it_had(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    common = ["--seconds", str(SECONDS), "--profile", str(REPO / "profiles/generic_dc.yaml"),
              "--contracts", str(REPO / "contracts")]  # fmt: skip
    scripted = tmp_path / "scripted"
    scenario_cli(["run", "OP-03", "--out", str(scripted), *common])
    manifest = json.loads((scripted / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["agent_kind"] == "scripted" and manifest["agent_note"] == SCRIPTED_NOTE
    assert "language_model" not in manifest
    assert f"agent: scripted_benign. {SCRIPTED_NOTE}" in capsys.readouterr().out

    _live_fake(monkeypatch)
    live = tmp_path / "live"
    scenario_cli(["run", "OP-03", "--agent", MODEL, "--out", str(live), *common])
    manifest = json.loads((live / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["agent_kind"] == "language_model"
    assert manifest["language_model"]["model"] == "claude-opus-5-5"
    assert manifest["language_model"]["usage"]["calls"] == 4
    assert "llm_transcript.jsonl" in manifest["files"] and not verify_bundle(live)
    assert "Language-model agent: anthropic/claude-opus-5-5" in capsys.readouterr().out

    monkeypatch.setattr(llm_providers, "live_transport", None)
    replayed = tmp_path / "replayed"
    scenario_cli(["run", "OP-03", "--agent", MODEL, "--out", str(replayed),
                  "--llm-replay", str(live), *common])  # fmt: skip
    again = json.loads((replayed / "manifest.json").read_text(encoding="utf-8"))
    assert again["language_model"]["mode"] == "replay"
    assert again["final_state_hash"] == manifest["final_state_hash"]
    for name in ("decisions.jsonl", "llm_transcript.jsonl"):
        assert (replayed / name).read_text() == (live / name).read_text()


@pytest.mark.req("ADC-AGT-001")
def test_the_commands_refuse_a_mix_and_an_unknown_agent(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit):
        bench_cli(["run", "--agent", "llm:nobody/x", "--allow-unfrozen"])
    status = bench_cli([
        "run", "--agent", "scripted_benign", "--agent", MODEL, "--scenario", "OP-03",
        "--seconds", "300", "--allow-unfrozen", "--gate", "null_gate",
        "--profile", str(REPO / "profiles/generic_dc.yaml"), "--contracts", str(REPO / "contracts"),
    ])  # fmt: skip
    assert status == 2 and "never beside them" in capsys.readouterr().err
    assert agent_cli(["list"]) == 0
    listed = capsys.readouterr().out
    assert "scripted_benign" in listed and all(f"llm:{p}/" in listed for p in PROVIDERS)


@pytest.mark.req("ADC-AGT-006")
def test_without_the_sdks_a_model_is_refused_with_how_to_install_them(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    real = llm_providers.importlib.import_module

    def missing(name: str) -> Any:
        if name in ("anthropic", "openai"):
            raise ImportError(name)
        return real(name)

    monkeypatch.setattr(llm_providers.importlib, "import_module", missing)
    for provider in ("anthropic", "openai"):
        with pytest.raises(LlmAgentError, match="uv sync --group llm"):
            llm_providers.live_transport(provider)


@pytest.mark.req("ADC-AGT-006")
def test_keys_come_from_the_environment_and_never_reach_a_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    secret = "sk-test-not-a-real-key-0123456789"
    seen: dict[str, Any] = {}

    class Completions:
        def create(self, **kwargs: Any) -> Any:
            seen["request"] = kwargs
            return types.SimpleNamespace(
                model="grok-test",
                choices=[types.SimpleNamespace(
                    finish_reason="stop",
                    message=types.SimpleNamespace(content="ok", tool_calls=None),
                )],
                usage=types.SimpleNamespace(prompt_tokens=5, completion_tokens=1),
            )  # fmt: skip

    class OpenAI:
        def __init__(self, api_key: str, base_url: str | None = None) -> None:
            seen.update(api_key=api_key, base_url=base_url)
            self.chat = types.SimpleNamespace(completions=Completions())

    fake = types.ModuleType("openai")
    fake.OpenAI = OpenAI  # type: ignore[attr-defined]
    fake.OpenAIError = RuntimeError  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "openai", fake)
    monkeypatch.delenv("ADC_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("XAI_API_KEY", raising=False)
    with pytest.raises(LlmAgentError, match="XAI_API_KEY"):
        llm_providers.live_transport("xai")
    with pytest.raises(LlmAgentError, match="ADC_LLM_BASE_URL"):
        llm_providers.live_transport("compatible")
    monkeypatch.setenv("XAI_API_KEY", secret)
    path = tmp_path / "t.jsonl"
    _run(LlmAgent("xai", "grok-test", Recorder(llm_providers.live_transport("xai"), path)))
    assert seen["api_key"] == secret and seen["base_url"] == "https://api.x.ai/v1"
    assert secret not in path.read_text(encoding="utf-8")


def test_the_anthropic_adapter_gives_a_reply_back_as_it_came() -> None:
    thinking = {"type": "thinking", "thinking": "", "signature": "sig"}
    use = {"type": "tool_use", "id": "t1", "name": "list_alarms", "input": {}}
    response = types.SimpleNamespace(
        content=[thinking, use], stop_reason="tool_use", model="claude-opus-5-5",
        usage=types.SimpleNamespace(input_tokens=7, output_tokens=3),
    )  # fmt: skip
    reply = llm_providers.anthropic_reply(response)
    assert reply["tool_calls"] == [{"id": "t1", "name": "list_alarms", "arguments": {}}]
    history = [
        {"role": "user", "text": "plant"}, {"role": "assistant", "reply": reply},
        {"role": "tool", "results": [{"id": "t1", "content": "[]", "error": True}]},
    ]  # fmt: skip
    request = {"model": "claude-opus-5-5", "max_tokens": 10, "system": "s", "tools": TOOL_SPECS,
               "history": history, "effort": "high"}  # fmt: skip
    kwargs = llm_providers.anthropic_request(request)
    assert kwargs["messages"][1] == {"role": "assistant", "content": [thinking, use]}
    assert kwargs["messages"][2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "t1",
        "content": "[]",
        "is_error": True,
    }
    assert kwargs["output_config"] == {"effort": "high"}
    assert {t["name"] for t in kwargs["tools"]} == set(TOOLS)


def test_the_openai_adapter_maps_tool_calls_and_stops() -> None:
    call = types.SimpleNamespace(
        id="x1", function=types.SimpleNamespace(name="get_points", arguments='{"tags": ["a"]}')
    )
    response = types.SimpleNamespace(
        model="gemini-test",
        choices=[types.SimpleNamespace(
            finish_reason="tool_calls",
            message=types.SimpleNamespace(content=None, tool_calls=[call]),
        )],
        usage=types.SimpleNamespace(prompt_tokens=9, completion_tokens=2),
    )  # fmt: skip
    reply = llm_providers.openai_reply(response)
    assert reply["stop"] == "tool_use" and reply["usage"] == {"input_tokens": 9, "output_tokens": 2}
    assert reply["tool_calls"] == [{"id": "x1", "name": "get_points", "arguments": {"tags": ["a"]}}]
    messages = llm_providers.openai_messages("s", [
        {"role": "user", "text": "plant"}, {"role": "assistant", "reply": reply},
        {"role": "tool", "results": [{"id": "x1", "content": "[]", "error": False}]},
    ])  # fmt: skip
    assert messages[0] == {"role": "system", "content": "s"}
    assert messages[2]["tool_calls"][0]["function"] == {
        "name": "get_points",
        "arguments": '{"tags": ["a"]}',
    }
    assert messages[3] == {"role": "tool", "tool_call_id": "x1", "content": "[]"}
    filtered = types.SimpleNamespace(choices=[types.SimpleNamespace(
        finish_reason="content_filter", message=types.SimpleNamespace(content="", tool_calls=None)
    )])  # fmt: skip
    assert llm_providers.openai_reply(filtered)["stop"] == "refusal"


@pytest.mark.req("ADC-AGT-005")
def test_the_recorded_example_replays_as_its_readme_says(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    example = REPO / "examples/llm-agent"
    readme = (example / "README.md").read_text(encoding="utf-8")
    command = readme.split("```sh\n", 1)[1].split("```", 1)[0].replace("\\\n", " ").split()
    assert command[:4] == ["uv", "run", "agentic-datacenter", "scenario"]
    arguments = command[4:]
    arguments[arguments.index("--out") + 1] = str(tmp_path / "out")
    monkeypatch.chdir(REPO)
    monkeypatch.setattr(llm_providers, "live_transport", None)  # no model may be called
    assert scenario_cli(arguments) == 0
    printed = capsys.readouterr().out.splitlines()
    shown = readme.split("```text\n", 1)[1].split("```", 1)[0].splitlines()
    assert printed[:2] == shown[:2]
    manifest = json.loads((tmp_path / "out/manifest.json").read_text(encoding="utf-8"))
    assert manifest["agent_kind"] == "language_model"
    assert manifest["language_model"]["mode"] == "replay"
    replies = [json.loads(t)["reply"] for t in (example / "OP-03.jsonl").read_text().splitlines()]
    assert all("not a model" in r["model"] for r in replies)
