"""Drift parser — extract_tool_calls / repair_arguments / normalize_tool_name.

Same battle the legacy ``core/llm_model.py`` parser fights, but the
return shape is internal ``ToolCall`` dicts instead of OpenAI wire
format. The cases here mirror real model outputs we've observed in the
wild — Gemma's three dialects, Qwen3-Coder's XML, the Hermes JSON
envelope, plus the malformed inputs that used to drop calls silently.
"""

from __future__ import annotations

import json

from jaeger_os.agent.drift_parser import (
    extract_tool_calls,
    normalize_tool_name,
    repair_arguments,
)


# ── extract_tool_calls — happy paths ───────────────────────────────


def test_extract_returns_empty_when_no_xml_present():
    assert extract_tool_calls("just a plain answer, no tools") == []


def test_extract_returns_empty_when_only_partial_marker_present():
    """Bare '<' shouldn't trip the extractor — it requires a full pattern
    match to fire a call."""
    assert extract_tool_calls("a < b") == []


def test_extract_hermes_json_envelope():
    text = '<tool_call>{"name": "get_time", "arguments": {"tz": "UTC"}}</tool_call>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_time"
    assert calls[0]["arguments"] == {"tz": "UTC"}
    assert calls[0]["id"].startswith("drift_")


def test_extract_legacy_gemma_json_envelope():
    text = '<|tool_call|>{"name": "lookup", "arguments": {"q": "x"}}<|/tool_call|>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "lookup"
    assert calls[0]["arguments"] == {"q": "x"}


def test_extract_gemma_brace_args_form():
    text = '<|tool_call>call:get_time{tz:<|"|>UTC<|"|>}<tool_call|>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "get_time"
    assert calls[0]["arguments"] == {"tz": "UTC"}


def test_extract_gemma_paren_kwargs_form():
    text = "<|tool_call>call:write_file(path='/tmp/x.py', content='print(1)')<tool_call|>"
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "write_file"
    assert calls[0]["arguments"]["path"] == "/tmp/x.py"
    assert calls[0]["arguments"]["content"] == "print(1)"


def test_extract_qwen_xml_form():
    text = (
        "<tool_call>"
        "<function=search>"
        "<parameter=query>population of japan</parameter>"
        "<parameter=max_results>5</parameter>"
        "</function>"
        "</tool_call>"
    )
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "search"
    assert calls[0]["arguments"] == {
        "query": "population of japan",
        "max_results": "5",
    }
    assert calls[0]["id"].startswith("qwen_")


def test_extract_multiple_calls_in_one_response():
    text = (
        '<tool_call>{"name": "a", "arguments": {}}</tool_call>'
        ' some text in between '
        '<tool_call>{"name": "b", "arguments": {"k": 1}}</tool_call>'
    )
    calls = extract_tool_calls(text)
    assert [c["name"] for c in calls] == ["a", "b"]


# ── extract_tool_calls — malformed input ───────────────────────────


def test_extract_recovers_from_trailing_comma():
    text = '<tool_call>{"name": "x", "arguments": {"a": 1,},}</tool_call>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["arguments"] == {"a": 1}


def test_extract_recovers_from_gemma_quote_tokens():
    text = '<tool_call>{<|"|>name<|"|>:<|"|>recall<|"|>,<|"|>q<|"|>:<|"|>cats<|"|>}</tool_call>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "recall"
    # The flat-args style — every remaining key is a tool arg.
    assert calls[0]["arguments"] == {"q": "cats"}


def test_extract_handles_flat_arg_style_no_arguments_key():
    """Gemma sometimes emits args at the top level instead of nested
    under ``arguments``."""
    text = '<tool_call>{"name": "write_file", "path": "/tmp/x", "content": "hi"}</tool_call>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["name"] == "write_file"
    assert calls[0]["arguments"] == {"path": "/tmp/x", "content": "hi"}


def test_extract_handles_double_encoded_arguments_string():
    text = '<tool_call>{"name": "x", "arguments": "{\\"a\\": 1}"}</tool_call>'
    calls = extract_tool_calls(text)
    assert len(calls) == 1
    assert calls[0]["arguments"] == {"a": 1}


def test_extract_drops_block_with_no_recoverable_name():
    text = '<tool_call>{"arguments": {"x": 1}}</tool_call>'
    assert extract_tool_calls(text) == []


# ── repair_arguments ───────────────────────────────────────────────


def test_repair_arguments_strict_json_passthrough():
    args, ok = repair_arguments('{"a": 1, "b": "two"}')
    assert ok is True
    assert args == {"a": 1, "b": "two"}


def test_repair_arguments_empty_input_is_recovered_empty():
    args, ok = repair_arguments("")
    assert ok is True
    assert args == {}
    args, ok = repair_arguments("none")
    assert ok is True
    assert args == {}


def test_repair_arguments_strips_trailing_commas():
    args, ok = repair_arguments('{"a": 1, "b": 2,}')
    assert ok is True
    assert args == {"a": 1, "b": 2}


def test_repair_arguments_swaps_single_quotes_when_safe():
    """Wholly single-quoted blob with no doubles → safe to swap."""
    args, ok = repair_arguments("{'a': 1, 'b': 'two'}")
    assert ok is True
    assert args == {"a": 1, "b": "two"}


def test_repair_arguments_double_encoded_string():
    """Local models occasionally emit a JSON string instead of a JSON
    object for the arguments — the repairer unwraps one level."""
    args, ok = repair_arguments('"{\\"x\\": 9}"')
    assert ok is True
    assert args == {"x": 9}


def test_repair_arguments_falls_through_to_gemma_loose_parser():
    args, ok = repair_arguments('{tz:<|"|>UTC<|"|>}')
    assert ok is True
    assert args.get("tz") == "UTC"


def test_repair_arguments_returns_unrecovered_on_total_garbage():
    args, ok = repair_arguments("@@@ not json at all $$$")
    # The fallback Gemma parser may or may not pluck pairs out of this —
    # the important assertion is that the API contract is honoured: we
    # always return a dict + a bool, never raise.
    assert isinstance(args, dict)
    assert isinstance(ok, bool)


# ── normalize_tool_name ────────────────────────────────────────────


def test_normalize_returns_input_when_exact_match():
    valid = frozenset({"get_time", "lookup"})
    assert normalize_tool_name("get_time", valid) == "get_time"


def test_normalize_collapses_case_and_hyphens():
    valid = frozenset({"get_time"})
    assert normalize_tool_name("Get-Time", valid) == "get_time"


def test_normalize_handles_camel_case():
    valid = frozenset({"get_time"})
    assert normalize_tool_name("GetTime", valid) == "get_time"


def test_normalize_strips_trailing_tool_suffix():
    valid = frozenset({"read_file"})
    assert normalize_tool_name("ReadFileTool", valid) == "read_file"
    assert normalize_tool_name("read_file_tool", valid) == "read_file"


def test_normalize_returns_unchanged_when_no_alias_matches():
    """No fuzzy guessing — an unrecognised name must surface as such so
    dispatch yields a clean 'unknown tool' error and the model retries."""
    valid = frozenset({"get_time"})
    assert normalize_tool_name("totally_different", valid) == "totally_different"


def test_normalize_empty_input_returns_empty():
    assert normalize_tool_name("", frozenset({"x"})) == ""
    assert normalize_tool_name("anything", frozenset()) == "anything"
