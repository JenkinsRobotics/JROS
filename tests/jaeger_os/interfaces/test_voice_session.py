"""Always-on voice — pure-logic tests.

The live mic loop needs hardware + Whisper + a model, so it can't be
unit-tested. What CAN be tested is the logic around it: the VoiceConfig
defaults, wake-phrase derivation, stop-phrase detection, the typed
trigger, VoiceController construction, and /voice argument parsing.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from rich.console import Console

from jaeger_os.core.schemas import VoiceConfig
from jaeger_os.interfaces.tui import slash_commands as slash
from jaeger_os.interfaces.tui.app import _wants_voice_mode
from jaeger_os.interfaces.tui.voice_session import (
    VoiceController,
    _wake_phrases,
    is_exit_phrase,
)


# ── VoiceConfig defaults ─────────────────────────────────────────────


def test_voice_config_defaults_everything_on() -> None:
    # A Jaeger is embodied — voice + wake + follow-up + barge-in all on.
    vc = VoiceConfig()
    assert vc.enabled and vc.wake_word and vc.follow_up and vc.barge_in
    assert vc.follow_up_seconds == 15.0


# ── wake-phrase derivation ───────────────────────────────────────────


def test_wake_phrases_cover_both_persona_and_system_names() -> None:
    """'Erin Jaeger' must wake on either name — the persona ('hey erin') for
    natural address, the system ('hey jaeger' + phonetic variants) because
    JaegerOS is the platform regardless of the per-instance name."""
    phrases = _wake_phrases("Erin Jaeger")
    # persona
    for prefix in ("ok", "okay", "hey"):
        assert f"{prefix} erin" in phrases
    # system + a phonetic variant Whisper commonly mishears
    assert "hey jaeger" in phrases
    assert "hey yeager" in phrases
    # banner-facing phrase shows the persona, not a phonetic variant
    assert phrases[-1] == "hey erin"


def test_wake_phrases_single_name_still_includes_system_default() -> None:
    phrases = _wake_phrases("Jarvis")
    assert "hey jarvis" in phrases
    assert "hey jaeger" in phrases   # system always reachable
    assert phrases[-1] == "hey jarvis"


def test_wake_phrases_empty_or_jaeger_falls_back_to_defaults() -> None:
    assert len(_wake_phrases("")) == 12
    assert "hey jaeger" in _wake_phrases("jaeger")


# ── stop-phrase detection ────────────────────────────────────────────


def test_exit_phrase_matches_mic_off_commands() -> None:
    for p in ("stop", "Stop.", " mic off ", "stop listening",
              "turn off the mic", "go to sleep"):
        assert is_exit_phrase(p), p


def test_exit_phrase_ignores_embedded_stop() -> None:
    for p in ("should I stop the server",
              "what does the exit code mean",
              "turn off the lights in the kitchen"):
        assert not is_exit_phrase(p), p


# ── typed natural-language trigger ───────────────────────────────────


def test_wants_voice_mode_on_activation_phrases() -> None:
    for p in ("mic on", "turn on mic", "turn on the microphone",
              "voice mode", "enable the mic"):
        assert _wants_voice_mode(p), p


def test_wants_voice_mode_ignores_long_coding_requests() -> None:
    long_req = ("write code to turn on the microphone via applescript "
                "and document the whole flow in the README please")
    assert not _wants_voice_mode(long_req)
    assert not _wants_voice_mode("tell me a joke")


# ── VoiceController construction ─────────────────────────────────────


def test_voice_controller_constructs_without_starting() -> None:
    # Construction must not touch hardware — start() does that.
    c = VoiceController(Console(file=open("/dev/null", "w")),
                        wake_name="Erin Jaeger")
    assert c.running is False
    assert c.barge_in_live is False  # only true after start() with speexdsp
    assert c.wake_word_phrase == "hey erin"


def test_voice_controller_carries_settings() -> None:
    c = VoiceController(Console(file=open("/dev/null", "w")),
                        wake_word=False, follow_up=False, barge_in=False)
    assert (c.wake_word, c.follow_up, c.barge_in) == (False, False, False)


def test_arm_interrupt_is_safe_before_start() -> None:
    # arm/disarm with no live STT must be no-ops, never raise — the REPL
    # calls them around every turn whether or not the mic came up.
    import threading
    c = VoiceController(Console(file=open("/dev/null", "w")))
    ev = threading.Event()
    c.arm_interrupt(ev)
    c.disarm_interrupt()


# ── /voice slash command ─────────────────────────────────────────────


def _ctx_with_tui() -> tuple[slash.SlashContext, MagicMock]:
    tui = MagicMock()
    ctx = slash.SlashContext(
        console=Console(file=open("/dev/null", "w"), width=80),
        instance_dir=Path("/tmp/fake_instance"),
        tui=tui,
    )
    return ctx, tui


def test_voice_command_no_args_shows_settings() -> None:
    ctx, tui = _ctx_with_tui()
    slash.dispatch("/voice", ctx)
    tui.voice_status_text.assert_called_once()


def test_voice_command_on_off_toggles_enabled() -> None:
    ctx, tui = _ctx_with_tui()
    slash.dispatch("/voice off", ctx)
    tui.apply_voice_setting.assert_called_with("enabled", False)
    slash.dispatch("/voice on", ctx)
    tui.apply_voice_setting.assert_called_with("enabled", True)


def test_voice_command_feature_toggles() -> None:
    ctx, tui = _ctx_with_tui()
    slash.dispatch("/voice bargein off", ctx)
    tui.apply_voice_setting.assert_called_with("barge_in", False)
    slash.dispatch("/voice wake on", ctx)
    tui.apply_voice_setting.assert_called_with("wake_word", True)
    slash.dispatch("/voice followup off", ctx)
    tui.apply_voice_setting.assert_called_with("follow_up", False)


def test_voice_command_without_tui_is_safe() -> None:
    ctx = slash.SlashContext(
        console=Console(file=open("/dev/null", "w"), width=80),
        instance_dir=Path("/tmp/fake_instance"),
    )
    result = slash.dispatch("/voice", ctx)  # must not raise
    assert result.quit is False
