from __future__ import annotations

from pydantic_ai.messages import ModelRequest, UserPromptPart

from jaeger_os.main import (
    _augment_with_session_context,
    _sanitize_history_messages,
    _session_state,
    _update_session_state_from_iter,
)


def test_session_state_tracks_calculation_result_from_skip_final() -> None:
    key = "test_session_state_calc"
    _session_state.pop(key, None)
    _update_session_state_from_iter(key, {
        "skipped": True,
        "first_decision": {"tool": "calculate", "args": {"expression": "47*23"}},
        "skipped_result": {"result": 1081},
    })

    assert _session_state[key]["last_calculation_result"] == 1081
    augmented = _augment_with_session_context(key, "Now multiply that result by 2.")
    assert "last_calculation_result: 1081" in augmented
    assert augmented.endswith("Now multiply that result by 2.")


def test_session_context_stays_empty_without_relevant_state() -> None:
    key = "test_session_state_empty"
    _session_state.pop(key, None)
    assert _augment_with_session_context(key, "Hello") == "Hello"


def test_history_sanitizer_removes_synthetic_context() -> None:
    effective = "[session context from prior tool results]\nlast_calculation_result: 1081\n[end session context]\n\nNow double that."
    messages = [ModelRequest(parts=[UserPromptPart(content=effective)])]

    sanitized = _sanitize_history_messages(
        messages,
        effective_text=effective,
        original_text="Now double that.",
    )

    assert sanitized[0].parts[0].content == "Now double that."
