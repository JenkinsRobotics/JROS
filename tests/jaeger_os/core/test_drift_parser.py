"""Drift tool-call parsing — quote-aware paren-kwarg extraction.

Regression cover for the `file_write` bug: Gemma emits tool calls as
``call:file_write(content='print('Hello')', path='x')`` — Python-style
kwargs whose string value itself contains the quote character. The old
``'([^']*)'`` regex truncated `content` at the first inner quote
(`content='print('` → `print(`), so every "write me a file" turn
produced a syntax error or failed arg validation.
"""

from __future__ import annotations

from jaeger_os.core.llm_model import _extract_drift_tool_calls, _parse_paren_args
import json


# ── _parse_paren_args — quote-aware ──────────────────────────────────


def test_single_quoted_value_containing_single_quotes():
    """The bug: content is Python code with single quotes, wrapped in
    single quotes. Must survive intact, not truncate to 'print('."""
    args = _parse_paren_args(
        "content='print('Hello, World!')', path='skills/hello.py'"
    )
    assert args["content"] == "print('Hello, World!')"
    assert args["path"] == "skills/hello.py"


def test_double_quoted_value_containing_single_quotes():
    args = _parse_paren_args(
        "content=\"print('Hello, World!')\", path='skills/hello.py'"
    )
    assert args["content"] == "print('Hello, World!')"
    assert args["path"] == "skills/hello.py"


def test_inner_comma_kwarg_does_not_false_split():
    """A value containing `, capture_output=True` must not be split as
    if `capture_output` were the next kwarg."""
    args = _parse_paren_args(
        "code='subprocess.run(['python'], capture_output=True)'"
    )
    assert args["code"] == "subprocess.run(['python'], capture_output=True)"


def test_simple_kwargs_still_parse():
    assert _parse_paren_args("key='x'") == {"key": "x"}
    assert _parse_paren_args("timezone='Asia/Shanghai'") == {"timezone": "Asia/Shanghai"}


def test_bare_scalar_coercion():
    args = _parse_paren_args("count=3, ratio=0.5, flag=true, note='hi'")
    assert args == {"count": 3, "ratio": 0.5, "flag": True, "note": "hi"}


def test_escaped_quote_in_value():
    args = _parse_paren_args(r"content='it\'s fine'")
    assert args["content"] == "it's fine"


# ── _extract_drift_tool_calls — end to end ───────────────────────────


def test_drift_extract_paren_form_file_write():
    """The full Gemma markup → an OpenAI-style tool_call with intact args."""
    text = (
        "<|tool_call>call:file_write(content='print('hi')', "
        "path='skills/h.py')<tool_call|>"
    )
    calls = _extract_drift_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "file_write"
    parsed = json.loads(calls[0]["function"]["arguments"])
    assert parsed["content"] == "print('hi')"
    assert parsed["path"] == "skills/h.py"


def test_drift_extract_tool_call_block_with_gemma_quote_tokens():
    """Regression: Gemma emits a <tool_call> JSON block but wraps string
    values in its own quote tokens (<|"|>). json.loads choked on those,
    so the whole tool call was silently dropped — the value never ran.
    They must normalize to real quotes and the call must survive."""
    text = (
        '<tool_call>\n{"name": "computer_type_text", "arguments": '
        '{"text":<|"|>https://example.com/x?q=a+b<|"|>}}\n</tool_call>'
    )
    calls = _extract_drift_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["function"]["name"] == "computer_type_text"
    parsed = json.loads(calls[0]["function"]["arguments"])
    assert parsed["text"] == "https://example.com/x?q=a+b"
