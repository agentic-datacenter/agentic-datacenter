"""The providers that serve a language-model agent: two adapters for five names (ADR 0035).

``anthropic`` goes through the Anthropic SDK and its Messages API. ``openai``,
``gemini``, ``xai`` and ``compatible`` go through the OpenAI SDK and the Chat
Completions API, which Gemini and Grok also offer at an endpoint of their own,
and which most local servers offer too.

Neither SDK is a dependency of the simulator. They are the optional group
``llm`` (``uv sync --group llm``), imported only when a model is called
(ADC-AGT-006). A run replayed from its transcript imports neither.

Every function here but :func:`live_transport` and the two ``_call`` functions
is pure, so the translation to and from each API is tested without a network.
"""

from __future__ import annotations

import importlib
import json
import os
from collections.abc import Mapping, Sequence
from typing import Any

from agentic_datacenter.scenarios.llm_agent import LlmAgentError, Transport

#: The endpoint and the key of each provider served through the OpenAI SDK.
OPENAI_STYLE: Mapping[str, tuple[str | None, str]] = {
    "openai": (None, "OPENAI_API_KEY"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai/", "GEMINI_API_KEY"),
    "xai": ("https://api.x.ai/v1", "XAI_API_KEY"),
    "compatible": (None, "ADC_LLM_API_KEY"),
}
#: Overrides the endpoint of any provider, and is required by ``compatible``.
BASE_URL_VARIABLE = "ADC_LLM_BASE_URL"
INSTALL_HINT = "the language-model agent needs the optional SDKs: uv sync --group llm"


def _sdk(name: str) -> Any:
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        raise LlmAgentError(f"{INSTALL_HINT} ({name} is not installed)") from exc


def _dump(block: Any) -> dict[str, Any]:
    """Return an SDK content block as the plain dict the API accepts back."""
    if isinstance(block, Mapping):
        return dict(block)
    for method in ("to_dict", "model_dump"):
        dump = getattr(block, method, None)
        if callable(dump):
            dumped = dump(exclude_none=True) if method == "model_dump" else dump()
            return {k: v for k, v in dict(dumped).items() if v is not None}
    raise TypeError(f"cannot record a content block of type {type(block).__name__}")


def _get(value: Any, key: str, default: Any = None) -> Any:
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


# --- Anthropic ---------------------------------------------------------------------------


def anthropic_tools(specs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return the tools as the Messages API takes them."""
    return [
        {"name": s["name"], "description": s["description"], "input_schema": s["parameters"]}
        for s in specs
    ]


def anthropic_messages(history: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return a conversation as Messages API messages.

    A reply from Anthropic is given back exactly as it came, thinking blocks
    and all, as the API asks.
    """
    out: list[dict[str, Any]] = []
    for turn in history:
        if turn["role"] == "user":
            out.append({"role": "user", "content": turn["text"]})
        elif turn["role"] == "assistant":
            reply = turn["reply"]
            raw = reply.get("raw")
            if isinstance(raw, Mapping) and raw.get("provider") == "anthropic":
                out.append({"role": "assistant", "content": list(raw["content"])})
                continue
            content: list[dict[str, Any]] = []
            if reply.get("text"):
                content.append({"type": "text", "text": reply["text"]})
            for call in reply.get("tool_calls") or []:
                content.append({
                    "type": "tool_use", "id": call["id"], "name": call["name"],
                    "input": call["arguments"] if isinstance(call["arguments"], dict) else {},
                })  # fmt: skip
            out.append({"role": "assistant", "content": content})
        else:
            out.append({
                "role": "user",
                "content": [
                    {"type": "tool_result", "tool_use_id": r["id"], "content": r["content"],
                     **({"is_error": True} if r.get("error") else {})}
                    for r in turn["results"]
                ],
            })  # fmt: skip
    return out


def anthropic_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the keyword arguments of ``client.messages.create`` for *request*."""
    kwargs: dict[str, Any] = {
        "model": request["model"],
        "max_tokens": int(request["max_tokens"]),
        "system": request["system"],
        "tools": anthropic_tools(request["tools"]),
        "messages": anthropic_messages(request["history"]),
    }
    if request.get("effort"):
        kwargs["output_config"] = {"effort": request["effort"]}
    return kwargs


def anthropic_reply(response: Any) -> dict[str, Any]:
    """Return a Messages API response as a reply."""
    blocks = [_dump(b) for b in _get(response, "content", [])]
    text = "".join(str(b.get("text", "")) for b in blocks if b.get("type") == "text")
    calls = [
        {"id": b["id"], "name": b["name"], "arguments": b.get("input")}
        for b in blocks
        if b.get("type") == "tool_use"
    ]
    usage = _get(response, "usage")
    return {
        "text": text,
        "tool_calls": calls,
        "stop": str(_get(response, "stop_reason") or ""),
        "model": str(_get(response, "model") or ""),
        "usage": {
            "input_tokens": int(_get(usage, "input_tokens", 0) or 0),
            "output_tokens": int(_get(usage, "output_tokens", 0) or 0),
        },
        "raw": {"provider": "anthropic", "content": blocks},
    }


def _anthropic_call(request: Mapping[str, Any]) -> dict[str, Any]:
    anthropic = _sdk("anthropic")
    base = os.environ.get(BASE_URL_VARIABLE)
    try:
        client = anthropic.Anthropic(**({"base_url": base} if base else {}))
        response = client.messages.create(**anthropic_request(request))
    except anthropic.AnthropicError as exc:
        raise LlmAgentError(f"anthropic: {type(exc).__name__}: {exc}") from exc
    return anthropic_reply(response)


# --- OpenAI and the endpoints that speak its API -----------------------------------------


def openai_tools(specs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return the tools as the Chat Completions API takes them."""
    return [
        {
            "type": "function",
            "function": {
                "name": s["name"], "description": s["description"], "parameters": s["parameters"],
            },
        }
        for s in specs
    ]  # fmt: skip


def openai_messages(system: str, history: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return a conversation as Chat Completions messages."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for turn in history:
        if turn["role"] == "user":
            out.append({"role": "user", "content": turn["text"]})
        elif turn["role"] == "assistant":
            reply = turn["reply"]
            message: dict[str, Any] = {"role": "assistant", "content": reply.get("text") or None}
            calls = reply.get("tool_calls") or []
            if calls:
                message["tool_calls"] = [
                    {
                        "id": c["id"], "type": "function",
                        "function": {
                            "name": c["name"],
                            "arguments": c["arguments"] if isinstance(c["arguments"], str)
                            else json.dumps(c["arguments"], sort_keys=True),
                        },
                    }
                    for c in calls
                ]  # fmt: skip
            out.append(message)
        else:
            out += [
                {"role": "tool", "tool_call_id": r["id"], "content": r["content"]}
                for r in turn["results"]
            ]
    return out


def openai_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return the keyword arguments of ``client.chat.completions.create`` for *request*.

    No length is sent: the endpoints that speak this API do not agree on its
    name, and the call budget bounds a run.
    """
    return {
        "model": request["model"],
        "messages": openai_messages(request["system"], request["history"]),
        "tools": openai_tools(request["tools"]),
    }


def openai_reply(response: Any) -> dict[str, Any]:
    """Return a Chat Completions response as a reply."""
    choice = (_get(response, "choices") or [None])[0]
    message = _get(choice, "message")
    calls = []
    for call in _get(message, "tool_calls") or []:
        function = _get(call, "function")
        text = str(_get(function, "arguments") or "{}")
        try:
            arguments: Any = json.loads(text)
        except json.JSONDecodeError:
            arguments = text  # kept as given; the agent answers it with an error
        calls.append({"id": str(_get(call, "id")), "name": str(_get(function, "name")),
                      "arguments": arguments})  # fmt: skip
    finish = str(_get(choice, "finish_reason") or "")
    stop = {"length": "max_tokens", "content_filter": "refusal", "tool_calls": "tool_use"}.get(
        finish, finish
    )
    usage = _get(response, "usage")
    return {
        "text": str(_get(message, "content") or ""),
        "tool_calls": calls,
        "stop": stop,
        "model": str(_get(response, "model") or ""),
        "usage": {
            "input_tokens": int(_get(usage, "prompt_tokens", 0) or 0),
            "output_tokens": int(_get(usage, "completion_tokens", 0) or 0),
        },
    }


def openai_endpoint(provider: str) -> tuple[str | None, str | None]:
    """Return the base URL and the key of *provider*, from the environment.

    Raises:
        LlmAgentError: If ``compatible`` has no base URL, or a hosted provider no key.
    """
    default_base, variable = OPENAI_STYLE[provider]
    base = os.environ.get(BASE_URL_VARIABLE) or default_base
    key = os.environ.get(variable)
    if provider == "compatible":
        if not base:
            raise LlmAgentError(f"llm:compatible needs its endpoint in {BASE_URL_VARIABLE}")
        return base, key or "not-needed"
    if not key:
        raise LlmAgentError(f"llm:{provider} needs its API key in {variable}")
    return base, key


def _openai_call(provider: str, request: Mapping[str, Any]) -> dict[str, Any]:
    openai = _sdk("openai")
    base, key = openai_endpoint(provider)
    try:
        client = openai.OpenAI(api_key=key, **({"base_url": base} if base else {}))
        response = client.chat.completions.create(**openai_request(request))
    except openai.OpenAIError as exc:
        raise LlmAgentError(f"{provider}: {type(exc).__name__}: {exc}") from exc
    return openai_reply(response)


def live_transport(provider: str) -> Transport:
    """Return the transport that calls *provider*'s model over the network."""
    if provider == "anthropic":
        _sdk("anthropic")
        return _anthropic_call
    if provider in OPENAI_STYLE:
        _sdk("openai")
        openai_endpoint(provider)

        def call(request: Mapping[str, Any]) -> dict[str, Any]:
            return _openai_call(provider, request)

        return call
    raise LlmAgentError(f"no such provider: {provider}")
