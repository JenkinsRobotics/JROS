"""``AnthropicAdapter`` — unit tests with an injected fake SDK client.

No real network. No real ``anthropic`` SDK objects beyond what we
construct ourselves. The translation + parse logic is the public
contract under test.
"""

from __future__ import annotations

import threading
from types import SimpleNamespace
from typing import Any

import pytest
from pydantic import BaseModel, Field

from jaeger_os.agent import AnthropicAdapter
from jaeger_os.agent.tool_schema import ToolDef


# ── fake SDK client ────────────────────────────────────────────────


class _FakeMessages:
    def __init__(self, response: Any):
        self._response = response
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs: Any) -> Any:
        self.last_kwargs = kwargs
        return self._response


class _FakeClient:
    def __init__(self, response: Any):
        self.messages = _FakeMessages(response)


def _mk_response(
    text_blocks: list[str] | None = None,
    tool_uses: list[dict[str, Any]] | None = None,
    usage: dict[str, int] | None = None,
) -> Any:
    """Build an object shaped enough like ``anthropic.types.Message`` for
    ``parse_response`` — ``content`` is a list of blocks with ``type``,
    ``text``/``id``/``name``/``input`` attrs."""
    blocks: list[Any] = []
    for t in (text_blocks or []):
        blocks.append(SimpleNamespace(type="text", text=t))
    for tu in (tool_uses or []):
        blocks.append(SimpleNamespace(
            type="tool_use",
            id=tu["id"],
            name=tu["name"],
            input=tu.get("input", {}),
        ))
    usage_obj = SimpleNamespace(**(usage or {})) if usage is not None else None
    return SimpleNamespace(content=blocks, usage=usage_obj)


# ── tool / args fixtures ───────────────────────────────────────────


class _Args(BaseModel):
    x: int = Field(ge=0)


def _mk_tool() -> ToolDef:
    return ToolDef(
        name="bump",
        description="Bump a counter.",
        args_model=_Args,
        fn=lambda x: {"x_plus_one": x + 1},
    )


# ── format_messages ────────────────────────────────────────────────


def test_format_messages_splits_system_into_top_level():
    adapter = AnthropicAdapter(api_key="dummy", prompt_caching=False, client=_FakeClient(_mk_response(["ok"])))
    out = adapter.format_messages(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        system="you are a robot",
    )
    assert out["system"] == "you are a robot"
    assert out["messages"] == [{"role": "user", "content": "hi"}]
    assert out["model"] == adapter.model
    assert "tools" not in out


def test_format_messages_rolls_internal_system_into_top_level_system():
    """Internal ``system`` messages (e.g. mid-conversation reminders) get
    appended to the top-level system parameter — Anthropic doesn't carry
    system inside the conversation."""
    adapter = AnthropicAdapter(api_key="dummy", prompt_caching=False, client=_FakeClient(_mk_response(["ok"])))
    out = adapter.format_messages(
        messages=[
            {"role": "system", "content": "extra rule"},
            {"role": "user", "content": "hi"},
        ],
        tools=[],
        system="base prompt",
    )
    assert "base prompt" in out["system"]
    assert "extra rule" in out["system"]
    # Conversation has only the user — the system got pulled out.
    assert [m["role"] for m in out["messages"]] == ["user"]


def test_format_messages_translates_assistant_tool_calls_to_tool_use_blocks():
    adapter = AnthropicAdapter(api_key="dummy", prompt_caching=False, client=_FakeClient(_mk_response(["ok"])))
    out = adapter.format_messages(
        messages=[
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": "calling",
                "tool_calls": [
                    {"id": "c1", "name": "bump", "arguments": {"x": 1}},
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "c1",
                "name": "bump",
                "content": '{"x_plus_one": 2}',
            },
        ],
        tools=[],
        system="",
    )
    msgs = out["messages"]
    # user, assistant(text + tool_use), user(tool_result)
    assert [m["role"] for m in msgs] == ["user", "assistant", "user"]
    assistant_blocks = msgs[1]["content"]
    assert any(b.get("type") == "text" for b in assistant_blocks)
    tool_use = next(b for b in assistant_blocks if b.get("type") == "tool_use")
    assert tool_use["id"] == "c1"
    assert tool_use["name"] == "bump"
    assert tool_use["input"] == {"x": 1}
    tool_result_block = msgs[2]["content"][0]
    assert tool_result_block["type"] == "tool_result"
    assert tool_result_block["tool_use_id"] == "c1"


def test_format_messages_merges_parallel_tool_results_into_one_user_turn():
    """Anthropic requires parallel tool results to ride together on a
    single user message. The adapter merges consecutive internal tool
    messages."""
    adapter = AnthropicAdapter(api_key="dummy", prompt_caching=False, client=_FakeClient(_mk_response(["ok"])))
    out = adapter.format_messages(
        messages=[
            {"role": "tool", "tool_call_id": "a", "name": "x", "content": "1"},
            {"role": "tool", "tool_call_id": "b", "name": "x", "content": "2"},
            {"role": "tool", "tool_call_id": "c", "name": "x", "content": "3"},
        ],
        tools=[],
        system="",
    )
    assert len(out["messages"]) == 1
    blocks = out["messages"][0]["content"]
    assert len(blocks) == 3
    assert [b["tool_use_id"] for b in blocks] == ["a", "b", "c"]


def test_format_messages_includes_tools_when_provided():
    adapter = AnthropicAdapter(api_key="dummy", prompt_caching=False, client=_FakeClient(_mk_response(["ok"])))
    out = adapter.format_messages(
        messages=[{"role": "user", "content": "hi"}],
        tools=[_mk_tool()],
        system="",
    )
    assert "tools" in out
    assert out["tools"][0]["name"] == "bump"
    assert "input_schema" in out["tools"][0]


def test_format_messages_unknown_role_raises():
    adapter = AnthropicAdapter(api_key="dummy", prompt_caching=False, client=_FakeClient(_mk_response(["ok"])))
    with pytest.raises(ValueError, match="unknown message role"):
        adapter.format_messages(
            messages=[{"role": "wizard", "content": "bzzt"}],
            tools=[],
            system="",
        )


# ── prompt caching markers ─────────────────────────────────────────


def test_prompt_caching_marks_system_and_last_user():
    adapter = AnthropicAdapter(api_key="dummy", prompt_caching=True, client=_FakeClient(_mk_response(["ok"])))
    out = adapter.format_messages(
        messages=[
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "second"},
        ],
        tools=[],
        system="rules",
    )
    # System is wrapped into a cache-controlled block.
    assert isinstance(out["system"], list)
    assert out["system"][0]["cache_control"] == {"type": "ephemeral"}
    # The trailing user turn became a list with a cached text block.
    last_user = out["messages"][-1]
    assert isinstance(last_user["content"], list)
    assert last_user["content"][-1]["cache_control"] == {"type": "ephemeral"}


def test_prompt_caching_off_leaves_payload_plain():
    adapter = AnthropicAdapter(api_key="dummy", prompt_caching=False, client=_FakeClient(_mk_response(["ok"])))
    out = adapter.format_messages(
        messages=[{"role": "user", "content": "hi"}],
        tools=[],
        system="rules",
    )
    assert out["system"] == "rules"
    assert out["messages"][0]["content"] == "hi"


# ── call + parse_response ──────────────────────────────────────────


def test_call_dispatches_to_client_with_merged_kwargs():
    fake = _FakeClient(_mk_response(["hi"]))
    adapter = AnthropicAdapter(api_key="dummy", client=fake)
    out = adapter.call(
        {"model": "x", "max_tokens": 4096, "messages": []},
        threading.Event(),
        temperature=0.7,  # extra kwarg
    )
    assert out is fake.messages._response
    assert fake.messages.last_kwargs is not None
    assert fake.messages.last_kwargs["temperature"] == 0.7
    assert fake.messages.last_kwargs["model"] == "x"


def test_parse_response_concatenates_text_blocks():
    adapter = AnthropicAdapter(api_key="dummy", client=_FakeClient(_mk_response(["hello, ", "world"])))
    raw = _mk_response(text_blocks=["hello, ", "world"])
    parsed = adapter.parse_response(raw)
    assert parsed["role"] == "assistant"
    assert parsed["content"] == "hello, world"
    assert "tool_calls" not in parsed


def test_parse_response_lifts_tool_use_blocks_to_internal_tool_calls():
    adapter = AnthropicAdapter(api_key="dummy", client=_FakeClient(_mk_response(["ok"])))
    raw = _mk_response(
        text_blocks=["calling bump"],
        tool_uses=[{"id": "c1", "name": "bump", "input": {"x": 3}}],
    )
    parsed = adapter.parse_response(raw)
    assert parsed["content"] == "calling bump"
    assert parsed["tool_calls"] is not None
    assert parsed["tool_calls"][0] == {
        "id": "c1",
        "name": "bump",
        "arguments": {"x": 3},
    }


def test_parse_response_stashes_usage_on_adapter():
    adapter = AnthropicAdapter(api_key="dummy", client=_FakeClient(_mk_response(["ok"])))
    raw = _mk_response(
        text_blocks=["ok"],
        usage={"input_tokens": 12, "output_tokens": 3, "cache_read_input_tokens": 2},
    )
    adapter.parse_response(raw)
    assert adapter.last_usage is not None
    assert adapter.last_usage["input_tokens"] == 12
    assert adapter.last_usage["output_tokens"] == 3
    assert adapter.last_usage["cache_read_input_tokens"] == 2


def test_parse_response_handles_empty_content():
    """Degenerate but possible: a response with no blocks at all. Don't
    crash — return an empty assistant message and let the loop decide
    what to do."""
    adapter = AnthropicAdapter(api_key="dummy", client=_FakeClient(_mk_response([])))
    parsed = adapter.parse_response(SimpleNamespace(content=[], usage=None))
    assert parsed["role"] == "assistant"
    assert parsed["content"] is None


# ── capabilities ───────────────────────────────────────────────────


def test_supports_returns_known_feature_flags():
    adapter = AnthropicAdapter(api_key="dummy", client=_FakeClient(_mk_response(["ok"])))
    assert adapter.supports("caching") is True
    assert adapter.supports("parallel_tools") is True
    assert adapter.supports("reasoning") is True
    assert adapter.supports("streaming") is False
    assert adapter.supports("vision") is False
    assert adapter.supports("nonsense") is False


def test_describe_includes_model_name():
    adapter = AnthropicAdapter(api_key="dummy", model="claude-foo", client=_FakeClient(_mk_response(["ok"])))
    assert "claude-foo" in adapter.describe()
    assert "anthropic" in adapter.describe()


# ── health_check ───────────────────────────────────────────────────


def test_health_check_returns_ok_when_client_responds():
    adapter = AnthropicAdapter(api_key="dummy", client=_FakeClient(_mk_response(["."])))
    health = adapter.health_check()
    assert health["ok"] is True
    assert "latency_s" in health


def test_health_check_returns_failure_on_client_exception():
    class _BrokenMessages:
        def create(self, **_):
            raise RuntimeError("boom")

    class _BrokenClient:
        messages = _BrokenMessages()

    adapter = AnthropicAdapter(api_key="dummy", client=_BrokenClient())
    health = adapter.health_check()
    assert health["ok"] is False
    assert "RuntimeError" in health["detail"]
    assert "boom" in health["detail"]
