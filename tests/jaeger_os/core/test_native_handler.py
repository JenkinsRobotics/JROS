"""Native per-model tool handling.

Gemma 4 and Qwen3-Coder each ship their own tool dialect in their GGUF
chat template. The native path feeds the template structured messages so
it renders the conversation in the model's OWN format — instead of the
legacy path's hand-rolled Hermes XML, which made the model read its past
actions in a foreign dialect.

Covers: the recursive Gemma brace-arg parser, the Qwen `<function=…>`
parser, and the native vs. legacy message conversion.
"""

from __future__ import annotations

import json

from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    SystemPromptPart,
    TextPart,
    ToolCallPart,
    ToolReturnPart,
    UserPromptPart,
)

from jaeger_os.core.llm_model import (
    LlamaCppModel,
    _extract_drift_tool_calls,
    _extract_qwen_tool_calls,
    _native_tools_enabled,
    _parse_gemma_args,
)


# ── _parse_gemma_args — recursive brace parser ───────────────────────


def test_gemma_args_does_not_drop_unquoted_keys() -> None:
    """The bug in the old _parse_loose_args: it returned on the first
    quoted pair and silently dropped every unquoted key after it."""
    args = _parse_gemma_args('query:<|"|>population of japan<|"|>,max_results:5')
    assert args == {"query": "population of japan", "max_results": 5}


def test_gemma_args_nested_object_and_array() -> None:
    args = _parse_gemma_args(
        'opts:{deep:true,n:3},tags:[<|"|>a<|"|>,<|"|>b<|"|>]'
    )
    assert args == {"opts": {"deep": True, "n": 3}, "tags": ["a", "b"]}


def test_gemma_args_scalar_coercion() -> None:
    args = _parse_gemma_args("count:7,ratio:0.5,flag:false,name:<|\"|>x<|\"|>")
    assert args == {"count": 7, "ratio": 0.5, "flag": False, "name": "x"}


def test_gemma_args_empty_is_empty_dict() -> None:
    assert _parse_gemma_args("") == {}
    assert _parse_gemma_args("{}") == {}


def test_gemma_args_braced_input() -> None:
    assert _parse_gemma_args('{n:1}') == {"n": 1}


# ── Gemma native tool call — end to end ──────────────────────────────


def test_extract_gemma_native_brace_call() -> None:
    text = '<|tool_call>call:web_search{query:<|"|>japan pop<|"|>,max_results:5}<tool_call|>'
    calls = _extract_drift_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "web_search"
    assert json.loads(calls[0]["function"]["arguments"]) == {
        "query": "japan pop", "max_results": 5,
    }


# ── Qwen3-Coder native tool call ─────────────────────────────────────


def test_extract_qwen_function_call() -> None:
    text = (
        "<tool_call>\n<function=get_weather>\n"
        "<parameter=location>\nTokyo\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    calls = _extract_qwen_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "get_weather"
    assert json.loads(calls[0]["function"]["arguments"]) == {"location": "Tokyo"}


def test_extract_qwen_multi_parameter() -> None:
    text = (
        "<tool_call>\n<function=file_write>\n"
        "<parameter=path>\nskills/h.py\n</parameter>\n"
        "<parameter=content>\nprint('hi')\n</parameter>\n"
        "</function>\n</tool_call>"
    )
    calls = _extract_qwen_tool_calls(text)
    assert len(calls) == 1
    args = json.loads(calls[0]["function"]["arguments"])
    assert args == {"path": "skills/h.py", "content": "print('hi')"}


def test_qwen_form_routes_through_drift_extractor() -> None:
    """_extract_drift_tool_calls recognises the Qwen dialect too."""
    text = "<tool_call>\n<function=get_time>\n</function>\n</tool_call>"
    calls = _extract_drift_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "get_time"


# ── native vs. legacy message conversion ─────────────────────────────


def _conversation() -> list:
    return [
        ModelRequest(parts=[
            SystemPromptPart(content="You are Lilith."),
            UserPromptPart(content="weather in Tokyo?"),
        ]),
        ModelResponse(parts=[
            ToolCallPart(tool_name="get_weather", args={"location": "Tokyo"},
                         tool_call_id="c1"),
        ]),
        ModelRequest(parts=[
            ToolReturnPart(tool_name="get_weather",
                           content={"temp": 74}, tool_call_id="c1"),
        ]),
        ModelResponse(parts=[TextPart(content="74F and clear.")]),
    ]


def test_native_gemma_emits_structured_tool_calls_and_responses() -> None:
    m = LlamaCppModel(None, model_name="gemma-4-26B-A4B-it-Q4_K_M.gguf")
    out = m._to_native_messages(_conversation())
    assistant = next(d for d in out if d["role"] == "assistant" and d.get("tool_calls"))
    assert assistant["tool_calls"][0]["function"]["name"] == "get_weather"
    assert assistant["tool_calls"][0]["function"]["arguments"] == {"location": "Tokyo"}
    tool = next(d for d in out if d["role"] == "tool")
    # Gemma reads `tool_responses`; it must NOT also carry `content`
    # (the template would double-print the result).
    assert tool["tool_responses"][0]["name"] == "get_weather"
    assert tool["tool_responses"][0]["response"] == {"temp": 74}
    assert "content" not in tool


def test_native_qwen_emits_openai_tool_message() -> None:
    """A non-Gemma model gets the OpenAI-shaped tool message (`content`),
    which Qwen3's template renders — no Gemma `tool_responses` key."""
    m = LlamaCppModel(None, model_name="Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf")
    assert m._is_gemma is False
    out = m._to_native_messages(_conversation())
    tool = next(d for d in out if d["role"] == "tool")
    assert "tool_responses" not in tool
    assert json.loads(tool["content"])["name"] == "get_weather"


def test_legacy_path_still_produces_hermes_xml() -> None:
    """The A/B baseline must be intact — legacy keeps tool history as
    Hermes XML inside user/assistant content."""
    m = LlamaCppModel(None, model_name="gemma-4-26B-A4B-it-Q4_K_M.gguf")
    out = m._to_legacy_messages(_conversation())
    blob = json.dumps(out)
    assert "<tool_call>" in blob
    assert "<tool_response>" in blob
    # legacy never emits structured tool_calls / tool role
    assert not any(d.get("tool_calls") for d in out)
    assert not any(d["role"] == "tool" for d in out)


# ── the JAEGER_NATIVE_TOOLS switch ───────────────────────────────────


def test_native_disabled_by_default(monkeypatch) -> None:
    """Legacy is the proven baseline — native is opt-in until a
    multi-sample A/B justifies flipping the default."""
    monkeypatch.delenv("JAEGER_NATIVE_TOOLS", raising=False)
    assert _native_tools_enabled() is False


def test_native_enabled_by_env(monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_NATIVE_TOOLS", "1")
    assert _native_tools_enabled() is True


def test_native_disabled_by_env(monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_NATIVE_TOOLS", "0")
    assert _native_tools_enabled() is False


def test_to_chat_messages_dispatches_on_the_flag(monkeypatch) -> None:
    m = LlamaCppModel(None, model_name="gemma-4-26B-A4B-it-Q4_K_M.gguf")
    convo = _conversation()
    monkeypatch.setenv("JAEGER_NATIVE_TOOLS", "1")
    assert any(d["role"] == "tool" for d in m._to_chat_messages(convo))
    monkeypatch.setenv("JAEGER_NATIVE_TOOLS", "0")
    assert not any(d["role"] == "tool" for d in m._to_chat_messages(convo))
