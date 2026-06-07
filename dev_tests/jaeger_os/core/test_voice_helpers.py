"""Voice helper tests for always-on mic filtering and reply cleanup."""

from __future__ import annotations

import pytest

from jaeger_os.core.voice import clean_voice_reply, is_non_speech_marker
from jaeger_os.core.voice import parse_gate, should_retry_ignored_followup


@pytest.mark.parametrize(
    "text",
    [
        "",
        "[BLANK_AUDIO]",
        "[SOUND]",
        "(wind blowing)",
        "(engine roaring)",
        "(engine revving)",
        "(sighs)",
        "(tapping)",
        "(clicking)",
        "[typing sounds]",
        "(clapping)",
        "(water splashing)",
        "(air whooshing)",
        "(keyboard clacking)",
        "(paper rustling)",
        "(upbeat music)",
        "(scissors snipping)",
        "(beeping) (clicking)",
        "computer click",
    ],
)
def test_non_speech_markers_drop_open_mic_noise(text: str) -> None:
    assert is_non_speech_marker(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "(yes)",
        "[no]",
        "can you hear me?",
        "(clicking) hey jaeger what time is it",
    ],
)
def test_non_speech_filter_keeps_real_short_answers(text: str) -> None:
    assert is_non_speech_marker(text) is False


@pytest.mark.parametrize(
    "text",
    ["[BLANK_AUDIO]", "(beeping)", "(tapping)", "(beeping) (clicking)"],
)
def test_active_followup_retry_does_not_retry_non_speech(text: str) -> None:
    assert should_retry_ignored_followup(
        text,
        retry_enabled=True,
        active_followup=True,
    ) is False


def test_active_followup_retry_keeps_real_followup() -> None:
    assert should_retry_ignored_followup(
        "thank you, can you also search that?",
        retry_enabled=True,
        active_followup=True,
    ) is True


# Single-pass gate replaces the two-call gate (operator-locked
# 2026-06-07).  The primary agent's system prompt teaches it to
# emit ``<ignore>`` or ``<reply>`` as the FIRST tokens of its
# response; parse_gate() parses that prefix.  See
# ``dev_docs/0.4.0_voice_gate_unification_prompt.md``.

def test_parse_gate_ignore_suppresses_speech() -> None:
    should_speak, text = parse_gate("<ignore>")
    assert should_speak is False
    assert text == ""


def test_parse_gate_reply_strips_tag_and_speaks() -> None:
    should_speak, text = parse_gate("<reply>It is 2:28 PM.")
    assert should_speak is True
    assert text == "It is 2:28 PM."


def test_parse_gate_missing_tag_defaults_to_speak() -> None:
    """Lenient default: a forgetful model that omits the tag still
    gets its reply spoken.  See module docstring of llm_gate.py for
    the rationale."""
    should_speak, text = parse_gate("It is 2:28 PM.")
    assert should_speak is True
    assert text == "It is 2:28 PM."


def test_parse_gate_ignore_drops_trailing_text() -> None:
    """The protocol says <ignore> means nothing else; if the model
    emits text after the tag, we still drop it — speaking it would
    violate the gate's contract."""
    should_speak, text = parse_gate(
        "<ignore>this was background tv noise"
    )
    assert should_speak is False
    assert text == ""


def test_clean_voice_reply_extracts_harmony_final() -> None:
    raw = (
        "<|channel|>analysis<|message|>thinking<|end|>"
        "<|channel|>final<|message|>It is 2:12 AM."
    )
    assert clean_voice_reply(raw) == "It is 2:12 AM."


def test_clean_voice_reply_strips_malformed_channel_tokens() -> None:
    raw = "<|channel>thought <channel|>It is 2:12 AM."
    assert clean_voice_reply(raw) == "It is 2:12 AM."


def test_clean_voice_reply_strips_think_blocks() -> None:
    assert clean_voice_reply("<think>private</think>Hello.") == "Hello."
