"""Session resume must not strip the agent's identity.

The bug: a resumed session is rebuilt from the episodic log by
``_episodic_to_messages`` as bare user/assistant text pairs — no
``SystemPromptPart``. pydantic-ai only injects the agent's system prompt when
message_history is *empty* (``UserPromptNode``: ``if not messages``), so every
resumed turn ran with no identity, no operating rules, no knowledge of what
Jaeger is. ``_ensure_system_prompt`` re-seats the live system prompt at the
head of any non-empty history before the turn runs.
"""

from __future__ import annotations

import pytest

from jaeger_os.core.prompts import MANDATORY_TOOL_RULES
from jaeger_os.main import (
    _ensure_system_prompt,
    _episodic_to_messages,
    _get_session_history,
    _pipeline,
)
from pydantic_ai.messages import (
    ModelRequest,
    SystemPromptPart,
    UserPromptPart,
)


@pytest.fixture()
def sys_prompt():
    """Install a known system prompt into the pipeline, then restore."""
    saved = _pipeline.get("system_prompt")
    value = "You are Erin, running on JaegerOS. TEST SYSTEM PROMPT."
    _pipeline["system_prompt"] = value
    try:
        yield value
    finally:
        _pipeline["system_prompt"] = saved


def _pairs(*answers: str) -> list:
    """A resumed history built the way production builds it — user/assistant
    text pairs through the real episodic reconstruction."""
    turns: list[dict] = []
    for i, answer in enumerate(answers):
        turns.append({"role": "user", "content": f"q{i}"})
        turns.append({"role": "assistant", "content": answer})
    return _episodic_to_messages(turns)


def _sys_parts(msg) -> list:
    return [p for p in getattr(msg, "parts", []) if isinstance(p, SystemPromptPart)]


def test_resumed_history_has_no_system_prompt_before_the_fix():
    """Baseline: the episodic reconstruction itself carries no system prompt
    — the gap the fix exists to close."""
    history = _pairs("a1", "a2")
    assert history
    assert _sys_parts(history[0]) == []


def test_resumed_history_gets_the_system_prompt(sys_prompt):
    history = _pairs("a1", "a2")
    _ensure_system_prompt(history)
    first = history[0]
    assert first.kind == "request"
    assert isinstance(first.parts[0], SystemPromptPart)
    assert first.parts[0].content == sys_prompt
    # the original first user prompt is preserved, right after the system one
    assert isinstance(first.parts[1], UserPromptPart)
    assert first.parts[1].content == "q0"


def test_is_idempotent(sys_prompt):
    history = _pairs("a1")
    _ensure_system_prompt(history)
    _ensure_system_prompt(history)
    assert len(_sys_parts(history[0])) == 1


def test_noop_when_first_request_already_has_a_system_prompt(sys_prompt):
    """A normal (non-resumed) turn 2 already carries the system prompt from
    pydantic-ai — it must not be duplicated or overwritten."""
    history = [ModelRequest(parts=[
        SystemPromptPart(content="existing prompt"),
        UserPromptPart(content="hi"),
    ])]
    _ensure_system_prompt(history)
    parts = _sys_parts(history[0])
    assert len(parts) == 1
    assert parts[0].content == "existing prompt"


def test_response_first_history_gets_a_standalone_system_request(sys_prompt):
    """An odd-length overflow trim can leave a ModelResponse at index 0 —
    the system prompt must still end up first."""
    pairs = _pairs("a1")
    history = [pairs[1]]  # the ModelResponse alone
    _ensure_system_prompt(history)
    assert len(history) == 2
    assert history[0].kind == "request"
    assert isinstance(history[0].parts[0], SystemPromptPart)
    assert history[1] is pairs[1]


def test_empty_history_is_a_noop(sys_prompt):
    history: list = []
    _ensure_system_prompt(history)
    assert history == []


def test_noop_when_no_system_prompt_is_configured():
    history = _pairs("a1")
    saved = _pipeline.get("system_prompt")
    _pipeline["system_prompt"] = ""
    try:
        _ensure_system_prompt(history)
    finally:
        _pipeline["system_prompt"] = saved
    assert _sys_parts(history[0]) == []


# ── no blind resume — a session starts clean ─────────────────────────


def test_get_session_history_does_not_blind_resume(monkeypatch):
    """A fresh session must NOT replay past turns from the episodic log —
    that bled stale, finished tasks into new conversations."""
    calls: list = []
    monkeypatch.setattr(
        "jaeger_os.core.memory.load_recent_turns",
        lambda *a, **k: calls.append((a, k)) or [],
    )
    history = _get_session_history("test-fresh-session-xyz")
    assert history == []
    assert calls == []  # load_recent_turns must never be reached


def test_get_session_history_accumulates_within_a_session():
    key = "test-accumulate-xyz"
    first = _get_session_history(key)
    first.append("turn-1")
    again = _get_session_history(key)
    assert again is first          # same live list across the session
    assert again == ["turn-1"]


def test_get_session_history_is_isolated_per_session_key():
    a = _get_session_history("test-iso-a-xyz")
    b = _get_session_history("test-iso-b-xyz")
    a.append("only-in-a")
    assert b == []


def test_recall_rule_directs_the_agent_to_retrieve_past_context():
    """With no blind resume, the prompt must tell the agent to fetch past
    context itself — facts via recall, conversations via search_memory."""
    text = MANDATORY_TOOL_RULES
    assert "clean context" in text.lower()
    assert "search_memory" in text
    assert "recall" in text.lower()
