"""Tool-call repair, name normalization, and dedup in the llama adapter.

Regression cover for the silent-failure path: llama-cpp-python parsed a
structured tool call but its ``arguments`` were not clean JSON, so the old
``_to_model_response`` loop turned a ``json.JSONDecodeError`` into ``args = {}``
and passed the raw tool name through unchanged — converting a parse failure
into a confident-looking *wrong* tool attempt. These tests pin the conservative
repair, the exact-variant name normalization, and the same-response dedup.
"""

from __future__ import annotations

from jaeger_os.core.llm_model import (
    LlamaCppModel,
    _normalize_tool_name,
    _repair_tool_call_arguments,
)
from pydantic_ai.messages import ToolCallPart


# ── _repair_tool_call_arguments ──────────────────────────────────────


def test_empty_and_null_blobs_are_recovered_empty():
    """An empty / whitespace / None / null argument blob is a legitimate
    empty call — recovered, not a failure."""
    for raw in ("", "   ", "None", "null", "NULL"):
        args, recovered = _repair_tool_call_arguments(raw)
        assert args == {}
        assert recovered is True


def test_trailing_comma_is_repaired():
    args, recovered = _repair_tool_call_arguments('{"path": "x.py", "n": 3,}')
    assert args == {"path": "x.py", "n": 3}
    assert recovered is True


def test_literal_control_char_in_string_is_repaired():
    """Local GGUF handlers sometimes emit a raw newline inside a string
    value — strict JSON rejects it, strict-off accepts it."""
    args, recovered = _repair_tool_call_arguments('{"code": "line1\nline2"}')
    assert args == {"code": "line1\nline2"}
    assert recovered is True


def test_gemma_quote_tokens_are_repaired():
    args, recovered = _repair_tool_call_arguments(
        '{"text": <|"|>hello world<|"|>}'
    )
    assert args == {"text": "hello world"}
    assert recovered is True


def test_wholly_single_quoted_blob_is_repaired():
    args, recovered = _repair_tool_call_arguments(
        "{'path': 'skills/h.py', 'count': 3}"
    )
    assert args == {"path": "skills/h.py", "count": 3}
    assert recovered is True


def test_mixed_quote_blob_is_left_for_tolerant_parser():
    """A value legitimately containing an apostrophe must not be corrupted
    by a blind single->double quote swap."""
    args, recovered = _repair_tool_call_arguments('{"msg": "it\'s fine"}')
    assert args == {"msg": "it's fine"}
    assert recovered is True


def test_double_encoded_arguments_string_is_unwrapped():
    """The arguments field is itself a JSON-encoded string of an object."""
    args, recovered = _repair_tool_call_arguments('"{\\"a\\": 1}"')
    assert args == {"a": 1}
    assert recovered is True


def test_unrepairable_blob_reports_failure():
    """No key/value structure at all -> empty dict, recovered is False so the
    caller can record the parse failure instead of swallowing it."""
    args, recovered = _repair_tool_call_arguments("{this is not json at all}")
    assert args == {}
    assert recovered is False


def test_well_formed_json_passes_through():
    args, recovered = _repair_tool_call_arguments('{"path": "a.py"}')
    assert args == {"path": "a.py"}
    assert recovered is True


# ── _normalize_tool_name ─────────────────────────────────────────────


_VALID = frozenset({"read_file", "write_file", "computer_use"})


def test_exact_name_is_unchanged():
    assert _normalize_tool_name("read_file", _VALID) == "read_file"


def test_case_and_separator_variants_normalize():
    assert _normalize_tool_name("Read_File", _VALID) == "read_file"
    assert _normalize_tool_name("read-file", _VALID) == "read_file"
    assert _normalize_tool_name("READ_FILE", _VALID) == "read_file"


def test_camelcase_variant_normalizes():
    assert _normalize_tool_name("ReadFile", _VALID) == "read_file"
    assert _normalize_tool_name("WriteFile", _VALID) == "write_file"


def test_trailing_tool_suffix_is_stripped():
    assert _normalize_tool_name("read_file_tool", _VALID) == "read_file"
    assert _normalize_tool_name("ReadFileTool", _VALID) == "read_file"


def test_unknown_name_is_left_unchanged():
    """No fuzzy matching — an unrecognised name passes through so pydantic-ai
    raises a clean 'unknown tool' error rather than us dispatching a guess."""
    assert _normalize_tool_name("frobnicate", _VALID) == "frobnicate"
    assert _normalize_tool_name("", _VALID) == ""


def test_empty_valid_set_is_a_noop():
    assert _normalize_tool_name("ReadFile", frozenset()) == "ReadFile"


# ── _to_model_response — end to end ──────────────────────────────────


def _model() -> LlamaCppModel:
    # _to_model_response never touches the Llama instance, so a stand-in
    # object is enough to exercise the conversion path.
    return LlamaCppModel(object(), "test-model")


def _completion(tool_calls: list[dict], content=None) -> dict:
    return {
        "choices": [{"message": {"content": content, "tool_calls": tool_calls}}],
        "usage": {},
    }


def _tc(name: str, arguments, tid: str = "call_1") -> dict:
    return {
        "id": tid,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


def _tool_parts(response) -> list[ToolCallPart]:
    return [p for p in response.parts if isinstance(p, ToolCallPart)]


def test_well_formed_call_is_unchanged():
    model = _model()
    resp = model._to_model_response(
        _completion([_tc("read_file", '{"path": "a.py"}')]),
        valid_tool_names=frozenset({"read_file"}),
    )
    parts = _tool_parts(resp)
    assert len(parts) == 1
    assert parts[0].tool_name == "read_file"
    assert LlamaCppModel._tool_call_args(parts[0]) == {"path": "a.py"}
    assert model.last_arg_repair_failures == []


def test_malformed_args_are_repaired_not_emptied():
    model = _model()
    resp = model._to_model_response(
        _completion([_tc("read_file", '{"path": "a.py",}')]),  # trailing comma
        valid_tool_names=frozenset({"read_file"}),
    )
    parts = _tool_parts(resp)
    assert len(parts) == 1
    assert LlamaCppModel._tool_call_args(parts[0]) == {"path": "a.py"}
    assert model.last_arg_repair_failures == []


def test_drifted_tool_name_is_normalized():
    model = _model()
    resp = model._to_model_response(
        _completion([_tc("ReadFile", '{"path": "a.py"}')]),
        valid_tool_names=frozenset({"read_file"}),
    )
    parts = _tool_parts(resp)
    assert len(parts) == 1
    assert parts[0].tool_name == "read_file"


def test_duplicate_calls_in_one_response_are_dropped():
    model = _model()
    resp = model._to_model_response(
        _completion([
            _tc("read_file", '{"path": "a.py"}', tid="c1"),
            _tc("read_file", '{"path": "a.py"}', tid="c2"),
        ]),
        valid_tool_names=frozenset({"read_file"}),
    )
    assert len(_tool_parts(resp)) == 1


def test_same_tool_different_args_is_not_a_duplicate():
    model = _model()
    resp = model._to_model_response(
        _completion([
            _tc("read_file", '{"path": "a.py"}', tid="c1"),
            _tc("read_file", '{"path": "b.py"}', tid="c2"),
        ]),
        valid_tool_names=frozenset({"read_file"}),
    )
    assert len(_tool_parts(resp)) == 2


def test_unrepairable_args_record_a_failure():
    model = _model()
    resp = model._to_model_response(
        _completion([_tc("read_file", "{this is not json at all}")]),
        valid_tool_names=frozenset({"read_file"}),
    )
    parts = _tool_parts(resp)
    assert len(parts) == 1
    assert LlamaCppModel._tool_call_args(parts[0]) == {}
    assert len(model.last_arg_repair_failures) == 1
    assert model.last_arg_repair_failures[0]["tool"] == "read_file"


def test_dict_arguments_pass_through():
    """llama-cpp-python occasionally hands back arguments already as a dict
    rather than a JSON string."""
    model = _model()
    resp = model._to_model_response(
        _completion([_tc("read_file", {"path": "a.py"})]),
        valid_tool_names=frozenset({"read_file"}),
    )
    parts = _tool_parts(resp)
    assert len(parts) == 1
    assert LlamaCppModel._tool_call_args(parts[0]) == {"path": "a.py"}
