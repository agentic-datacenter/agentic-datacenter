# SPDX-License-Identifier: MIT
"""A scripted stand-in for a language model, and the recording of the example run.

It is not a model. It answers as a careful operator would at the first
decision point of OP-03: it reads the chilled water setpoint and proposes a
step of half a kelvin up, then does nothing more. It shows what a run of a
model gives, and lets that run be replayed with no key and no network.

    python examples/llm-agent/stand_in.py     # writes examples/llm-agent/OP-03.jsonl

Replay it with the command in README.md beside this file.
"""

from __future__ import annotations

import json
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
CHWS = "cooling.chw_plant[CHW].chws_sp_c"
CHW_CONTRACT = "chw.set_supply_setpoint.v1"
#: The run the example is of; README.md gives the same.
ARGUMENTS = ["run", "OP-03", "--seconds", "900", "--agent", "llm:compatible/stand-in"]


def _reply(text: str = "", calls: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {
        "text": text,
        "tool_calls": calls or [],
        "stop": "tool_use" if calls else "end_turn",
        "model": "stand-in (scripted, not a model)",
        "usage": {"input_tokens": 0, "output_tokens": 0},
    }


def model(request: Mapping[str, Any]) -> dict[str, Any]:
    """Answer one request as the stand-in does."""
    history = request["history"]
    shown = json.loads(history[0]["text"].split("\n", 1)[1])
    if shown["time_s"] != 300:
        return _reply("The plant is steady; nothing to do.")
    rounds = sum(1 for turn in history if turn["role"] == "assistant")
    if rounds == 0:
        return _reply(calls=[{"id": "c1", "name": "get_points", "arguments": {"tags": [CHWS]}}])
    if rounds == 1:
        value = json.loads(history[-1]["results"][0]["content"])[0]["value"]
        step = {"setpoint_c": round(float(value) + 0.5, 3)}
        why = "The plant is healthy; a warmer setpoint saves chiller energy."
        return _reply(
            calls=[
                {
                    "id": "c2",
                    "name": "propose_action",
                    "arguments": {"contract_id": CHW_CONTRACT, "arguments": step, "rationale": why},
                }
            ]
        )
    return _reply("Proposed one step of half a kelvin.")


def record(out: Path = HERE / "OP-03.jsonl") -> int:
    """Run the example with the stand-in in place of a provider, and keep its transcript."""
    from agentic_datacenter.scenarios import llm_providers
    from agentic_datacenter.scenarios.cli import scenario

    real = llm_providers.live_transport
    llm_providers.live_transport = lambda provider: model  # type: ignore[assignment]
    try:
        with tempfile.TemporaryDirectory() as work:
            status = scenario([*ARGUMENTS, "--out", work, "--llm-transcripts", str(out)])
    finally:
        llm_providers.live_transport = real  # type: ignore[assignment]
    return status


if __name__ == "__main__":
    sys.exit(record())
