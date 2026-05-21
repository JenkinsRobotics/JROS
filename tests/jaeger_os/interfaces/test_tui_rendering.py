"""TUI turn rendering — the hermes-style chrome.

Each turn is framed like hermes: the user message between two rules on
a ``●`` bullet, live ``┊`` tool-activity lines while the agent works,
the reply in a ``✦ <name>`` rule-labelled box, and a pinned bottom
toolbar (model · context gauge · uptime · response time).
"""

from __future__ import annotations

from rich.console import Console

from jaeger_os.interfaces.tui.app import JaegerTUI, _dur, _kfmt


def _tui() -> JaegerTUI:
    tui = JaegerTUI(skip_model=True)
    tui.console = Console(width=90)
    return tui


# ── formatting helpers ───────────────────────────────────────────────


def test_kfmt_compacts_thousands() -> None:
    assert _kfmt(27800) == "27.8K"
    assert _kfmt(262144) == "262.1K"
    assert _kfmt(980) == "980"
    assert _kfmt(0) == "0"


def test_dur_is_compact() -> None:
    assert _dur(12) == "12s"
    assert _dur(240) == "4m"
    assert _dur(3690) == "1h 01m"


# ── turn header ──────────────────────────────────────────────────────


def test_turn_header_frames_the_user_message() -> None:
    tui = _tui()
    with tui.console.capture() as cap:
        tui._render_turn_header("hello there", source="text")
    out = cap.get()
    assert "hello there" in out
    assert "●" in out
    assert out.count("─") > 20          # a rule above and below


def test_turn_header_glyph_per_source() -> None:
    tui = _tui()
    for source, glyph in (("text", "●"), ("voice", "🎙"), ("goal", "◎")):
        with tui.console.capture() as cap:
            tui._render_turn_header("x", source=source)
        assert glyph in cap.get()


def test_turn_header_does_not_interpret_markup() -> None:
    # A user message containing Rich markup must render literally.
    tui = _tui()
    with tui.console.capture() as cap:
        tui._render_turn_header("delete [red]everything[/red]", source="text")
    assert "[red]everything[/red]" in cap.get()


# ── answer box ───────────────────────────────────────────────────────


def test_render_answer_labels_with_the_agent_name() -> None:
    tui = _tui()
    with tui.console.capture() as cap:
        tui._render_answer("the capital of France is Paris")
    out = cap.get()
    assert "the capital of France is Paris" in out
    assert "✦" in out                   # the answer-box label glyph


def test_render_answer_error_path() -> None:
    tui = _tui()
    with tui.console.capture() as cap:
        tui._render_answer("", error="model timed out")
    out = cap.get()
    assert "model timed out" in out
    assert "error" in out


def test_render_answer_empty_is_silent() -> None:
    tui = _tui()
    with tui.console.capture() as cap:
        tui._render_answer("   ")
    assert cap.get().strip() == ""


# ── live tool activity ───────────────────────────────────────────────


def test_tool_event_start_sets_activity_label() -> None:
    tui = _tui()
    tui._on_tool_event("start", "web_search", "weather", 0.0)
    assert tui._current_activity == "web_search"


def test_tool_event_done_prints_a_line_and_resets() -> None:
    tui = _tui()
    tui._on_tool_event("start", "web_search", "weather", 0.0)
    with tui.console.capture() as cap:
        tui._on_tool_event("done", "web_search", "", 1.4)
    out = cap.get()
    assert "┊" in out and "web_search" in out and "1.4s" in out
    assert tui._current_activity == "ruminating"


# ── status bar (pinned above the input line) ─────────────────────────


def test_status_line_has_the_hermes_segments() -> None:
    tui = _tui()
    tui.model_name = "qwen3.5:397b"
    tui._context_tokens = 27800
    tui._context_max = 262144
    tui._last_turn_s = 23.0
    bar = tui._status_line()
    assert "qwen3.5:397b" in bar
    assert "27.8K/262.1K" in bar
    assert "%" in bar and "█" in bar     # the context gauge
    assert "⏲ 23s" in bar


def test_status_line_shows_spinner_while_running() -> None:
    tui = _tui()
    tui._turn_running.set()
    tui._current_activity = "web_search"
    assert "web_search" in tui._status_line()


def test_prompt_message_puts_input_last() -> None:
    # The ❯ input fragment must be the final fragment — the input line
    # sits below the status bar (hermes layout).
    tui = _tui()
    frags = tui._prompt_message()
    assert frags[-1][1] == "❯ "
    assert any("─" in text for _style, text in frags)   # the bar rules


def test_prompt_message_is_just_the_caret_when_bar_hidden() -> None:
    from jaeger_os.interfaces.tui.theme import ACCENT_PTK
    tui = _tui()
    tui._statusbar_on = False
    frags = tui._prompt_message()
    assert frags == [(f"fg:{ACCENT_PTK} bold", "❯ ")]
