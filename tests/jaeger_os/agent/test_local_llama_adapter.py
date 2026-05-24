"""``LocalLlamaAdapter`` — in-process llama-cpp tests with a stub Llama.

No real GGUF, no real weights — a ``FakeLlama`` injected at
construction time exercises the chat-completion surface and the
drift-parser layering. The Phase 3 OpenAI adapter tests already cover
the wire format the parent class handles; this file focuses on what
the subclass adds.
"""

from __future__ import annotations

import json
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from jaeger_os.agent import LocalLlamaAdapter


class _FakeLlama:
    """Duck-types ``llama_cpp.Llama.create_chat_completion``."""

    def __init__(self, response: Any) -> None:
        self._response = response
        self.last_kwargs: dict[str, Any] | None = None

    def create_chat_completion(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        return self._response


def _mk_response(
    content: str | None = None,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """llama-cpp returns a plain dict (not a typed object). The adapter
    must parse that shape unchanged."""
    msg: dict[str, Any] = {"content": content}
    if tool_calls is not None:
        msg["tool_calls"] = [
            {
                "id": tc["id"],
                "type": "function",
                "function": {
                    "name": tc["name"],
                    "arguments": json.dumps(tc.get("arguments", {})),
                },
            }
            for tc in tool_calls
        ]
    return {
        "choices": [{"message": msg, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
    }


# ── construction ───────────────────────────────────────────────────


def test_constructor_requires_path_or_pre_loaded_llama():
    """Calling ``call()`` without either is the failure point — but
    construction is allowed so callers can build the adapter lazily."""
    a = LocalLlamaAdapter()
    with pytest.raises(ValueError, match="model_path"):
        a._ensure_client()


def test_explicit_llama_skips_load_entirely():
    fake = _FakeLlama(_mk_response("hi"))
    a = LocalLlamaAdapter(llama=fake)
    client = a._ensure_client()
    # The facade is built from the injected Llama, not from disk.
    assert client._llama is fake


def test_describe_uses_filename_when_path_given():
    a = LocalLlamaAdapter(model_path="/tmp/fake-model.gguf")
    assert "fake-model.gguf" in a.describe()
    assert "local-llama" in a.describe()


def test_provider_and_name_set_to_local_llama():
    """``/runtime`` shows the adapter's ``name``; pick precise labels so
    a user picking the local model sees 'local-llama' rather than the
    parent class's generic 'openai'."""
    a = LocalLlamaAdapter()
    assert a.name == "local-llama"
    assert a.provider == "local-llama"


# ── format → call → parse round-trip ───────────────────────────────


def test_call_dispatches_to_llama_with_strip_http_kwargs():
    """``api_key`` / ``base_url`` / ``timeout`` make no sense in-process
    — the facade must strip them before handing kwargs to llama-cpp."""
    fake = _FakeLlama(_mk_response("ack"))
    a = LocalLlamaAdapter(llama=fake)
    a.call(
        {"model": "x", "messages": [], "max_tokens": 64},
        threading.Event(),
        api_key="should-be-stripped",
        base_url="http://nowhere",
        timeout=30,
    )
    assert fake.last_kwargs is not None
    assert "api_key" not in fake.last_kwargs
    assert "base_url" not in fake.last_kwargs
    assert "timeout" not in fake.last_kwargs
    assert fake.last_kwargs["model"] == "x"


def test_parse_response_decodes_native_tool_calls():
    """When llama-cpp's chat handler DOES parse the call structurally,
    the parent's ``parse_response`` handles it — no drift fallback
    needed."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    raw = _mk_response(
        content=None,
        tool_calls=[{"id": "c1", "name": "get_time", "arguments": {"tz": "UTC"}}],
    )
    parsed = a.parse_response(raw)
    assert parsed["tool_calls"][0]["name"] == "get_time"
    assert parsed["tool_calls"][0]["arguments"] == {"tz": "UTC"}


def test_parse_response_salvages_drift_tool_calls_from_text():
    """When the chat handler leaves the call as text (Gemma 4 quirk),
    the drift parser must catch it AND the envelope must be stripped
    from the visible content."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    raw = _mk_response(
        content=(
            'thinking… '
            '<tool_call>{"name": "get_time", "arguments": {"tz": "PST"}}</tool_call>'
        ),
    )
    parsed = a.parse_response(raw)
    assert parsed["tool_calls"][0]["name"] == "get_time"
    assert parsed["tool_calls"][0]["arguments"] == {"tz": "PST"}
    assert "<tool_call>" not in (parsed["content"] or "")
    assert "thinking" in parsed["content"]


def test_parse_response_merges_structured_and_drift_calls():
    """Real-world: chat handler gives us ONE structured call and the
    model emits a SECOND one as text. The dispatcher needs both."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    raw = _mk_response(
        content='<tool_call>{"name": "second", "arguments": {"k": 1}}</tool_call>',
        tool_calls=[{"id": "c1", "name": "first", "arguments": {}}],
    )
    parsed = a.parse_response(raw)
    names = [tc["name"] for tc in parsed["tool_calls"]]
    assert names == ["first", "second"]


def test_parse_response_plain_text_passes_through_unchanged():
    """No `<` in the content means the drift parser never fires — fast
    path. Phase-8 also surfaces ``finish_reason`` on the message; the
    invariant is the content / role / no-tool-calls — finish_reason is
    additive."""
    fake = _FakeLlama(_mk_response("plain answer"))
    a = LocalLlamaAdapter(llama=fake)
    raw = _mk_response(content="plain answer")
    parsed = a.parse_response(raw)
    assert parsed["role"] == "assistant"
    assert parsed["content"] == "plain answer"
    assert "tool_calls" not in parsed


# ── capabilities + health ──────────────────────────────────────────


def test_supports_reports_in_process_capability_set():
    """No parallel-tools claim — the wire format doesn't guarantee it
    across the local-model menagerie. Streaming follows the flag."""
    a = LocalLlamaAdapter()
    assert a.supports("parallel_tools") is False
    assert a.supports("caching") is False
    assert a.supports("streaming") is False
    assert a.supports("vision") is False


def test_health_check_ok_when_client_constructable():
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    health = a.health_check()
    assert health["ok"] is True
    assert "loaded" in health["detail"]


def test_health_check_fails_when_no_path_and_no_llama():
    a = LocalLlamaAdapter()
    health = a.health_check()
    assert health["ok"] is False
    assert "model_path" in health["detail"]


# ── Jinja chat-template compatibility ───────────────────────────────


def test_call_decodes_tool_call_arguments_back_to_dict():
    """Regression: llama-cpp's Jinja chat templates (Qwen3.5, Gemma,
    Hermes) iterate ``tool_call.arguments|items`` — they need a dict,
    not the JSON-encoded string the OpenAI wire format uses. The facade
    must convert before passing to ``create_chat_completion`` or the
    template crashes with ``Can only get item pairs from a mapping``
    on the second turn of any tool-using conversation."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    a.call(
        {
            "model": "x",
            "messages": [
                {"role": "user", "content": "go"},
                {
                    "role": "assistant",
                    "content": None,
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {
                            "name": "bump",
                            # OpenAI wire format: JSON-encoded string.
                            "arguments": '{"x": 1, "y": "two"}',
                        },
                    }],
                },
                {
                    "role": "tool",
                    "tool_call_id": "c1",
                    "content": '{"ok": true}',
                },
            ],
        },
        threading.Event(),
    )
    assert fake.last_kwargs is not None
    sent_msg = fake.last_kwargs["messages"][1]
    sent_args = sent_msg["tool_calls"][0]["function"]["arguments"]
    # The decoded dict is what the Jinja template iterates.
    assert sent_args == {"x": 1, "y": "two"}
    assert isinstance(sent_args, dict)


def test_call_passes_through_already_dict_arguments():
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    a.call(
        {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [{
                        "function": {"name": "x", "arguments": {"already": "dict"}},
                    }],
                },
            ],
        },
        threading.Event(),
    )
    sent = fake.last_kwargs["messages"][0]["tool_calls"][0]["function"]["arguments"]
    assert sent == {"already": "dict"}


def test_call_handles_malformed_json_arguments_string_gracefully():
    """A drift-recovered tool call might carry malformed JSON. The
    facade must not crash — feed an empty dict to the template so
    rendering proceeds, even if the values are missing."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    a.call(
        {
            "messages": [
                {
                    "role": "assistant",
                    "tool_calls": [{
                        "function": {"name": "x", "arguments": "{not: json"},
                    }],
                },
            ],
        },
        threading.Event(),
    )
    sent = fake.last_kwargs["messages"][0]["tool_calls"][0]["function"]["arguments"]
    assert sent == {}


def test_in_process_call_forces_stale_timeout_to_none():
    """Regression: an in-process llama-cpp call CANNOT be cancelled
    safely — abandoning the worker thread corrupts the KV cache and
    the next call returns ``llama_decode -3``. Confirmed in production
    TUI on 2026-05-24. The adapter must override whatever the agent
    loop passed and force ``stale_timeout=None``."""
    import threading
    from unittest.mock import patch

    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)

    captured: dict[str, Any] = {}
    real_interruptible = __import__(
        "jaeger_os.agent.interrupt", fromlist=["interruptible_call"]
    ).interruptible_call

    def _spy(fn, ev, **kw):
        captured.update(kw)
        return real_interruptible(fn, ev, **kw)

    with patch("jaeger_os.agent.adapters.openai.interruptible_call", _spy):
        # The agent loop now defaults to stale_timeout=30.0; the adapter
        # must override that to None for the in-process path.
        a.call(
            {"model": "x", "messages": []},
            threading.Event(),
            stale_timeout=30.0,
        )
    assert captured["stale_timeout"] is None


def test_call_does_not_mutate_input_messages():
    """The facade walks messages defensively — the caller's list is
    NOT mutated, so re-using the same `formatted` dict across retries
    keeps working."""
    fake = _FakeLlama(_mk_response("ok"))
    a = LocalLlamaAdapter(llama=fake)
    msgs = [{
        "role": "assistant",
        "tool_calls": [{
            "function": {"name": "x", "arguments": '{"k": 1}'},
        }],
    }]
    a.call({"messages": msgs}, threading.Event())
    # Original input is still a JSON string — only the kwargs handed to
    # llama-cpp had the dict swap.
    assert msgs[0]["tool_calls"][0]["function"]["arguments"] == '{"k": 1}'
