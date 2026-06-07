"""Concurrent input — the hermes-style turn worker.

A turn runs on a background worker thread so the prompt_toolkit input
line stays live: you can type a follow-up, a slash command, or steer
while the agent is still working. ``display.busy_input_mode`` decides
what a typed message does mid-turn (interrupt / queue / steer).
"""

from __future__ import annotations

import threading
import time

from rich.console import Console

from jaeger_os.interfaces.tui.app import (
    _WORKER_SHUTDOWN,
    _format_coalesced_voice,
    _split_coalesced_voice,
    JaegerTUI,
)


# ── helpers ──────────────────────────────────────────────────────────


def _tui() -> JaegerTUI:
    tui = JaegerTUI(skip_model=True)
    tui.console = Console(file=open("/dev/null", "w"), width=100)
    return tui


def _run_worker(tui: JaegerTUI) -> threading.Thread:
    t = threading.Thread(target=tui._turn_worker, daemon=True)
    t.start()
    return t


def _stop_worker(tui: JaegerTUI, t: threading.Thread) -> None:
    tui._worker_stop.set()
    tui._turn_queue.put(_WORKER_SHUTDOWN)
    t.join(timeout=2.0)


def _wait(pred, timeout: float = 2.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if pred():
            return True
        time.sleep(0.02)
    return False


# ── the worker drains the queue ──────────────────────────────────────


def test_worker_runs_a_queued_turn() -> None:
    tui = _tui()
    calls: list = []
    tui.run_turn = lambda text, source="text": calls.append((source, text))
    tui._post_turn_goal_check = lambda: None
    t = _run_worker(tui)
    try:
        tui._turn_queue.put(("text", "hello"))
        assert _wait(lambda: calls == [("text", "hello")])
    finally:
        _stop_worker(tui, t)


def test_worker_runs_turns_in_order() -> None:
    tui = _tui()
    calls: list = []
    tui.run_turn = lambda text, source="text": calls.append(text)
    tui._post_turn_goal_check = lambda: None
    t = _run_worker(tui)
    try:
        for n in ("one", "two", "three"):
            tui._turn_queue.put(("text", n))
        assert _wait(lambda: calls == ["one", "two", "three"])
    finally:
        _stop_worker(tui, t)


def test_turn_running_flag_tracks_the_worker() -> None:
    tui = _tui()
    gate = threading.Event()
    seen_running = []

    def _slow(text, source="text"):
        seen_running.append(tui._turn_running.is_set())
        gate.wait(timeout=2.0)

    tui.run_turn = _slow
    tui._post_turn_goal_check = lambda: None
    t = _run_worker(tui)
    try:
        tui._turn_queue.put(("text", "x"))
        assert _wait(lambda: seen_running == [True])
        gate.set()
        assert _wait(lambda: not tui._turn_running.is_set())
    finally:
        gate.set()
        _stop_worker(tui, t)


# ── busy-input routing ───────────────────────────────────────────────


def test_submit_turn_enqueues_when_idle() -> None:
    tui = _tui()
    tui._submit_turn("text", "hi")
    assert tui._turn_queue.get_nowait() == ("text", "hi")


def test_submit_turn_queue_mode_appends() -> None:
    tui = _tui()
    tui._busy_mode = "queue"
    tui._turn_running.set()
    tui._submit_turn("text", "later")
    assert tui._turn_queue.get_nowait() == ("text", "later")


def test_submit_turn_interrupt_mode_cancels_and_enqueues() -> None:
    tui = _tui()
    tui._busy_mode = "interrupt"
    tui._turn_running.set()
    cancelled = []
    import jaeger_os.main as m
    orig = m.request_turn_cancel
    m.request_turn_cancel = lambda: cancelled.append(True)
    try:
        tui._submit_turn("text", "now")
    finally:
        m.request_turn_cancel = orig
    assert cancelled == [True]
    assert tui._turn_queue.get_nowait() == ("text", "now")


def test_submit_turn_steer_mode_interrupts_and_queues() -> None:
    # Steer stops the running turn at the next tool boundary (cancel)
    # and continues with the guidance — its partial work stays in
    # history, so the steered turn keeps full context.
    tui = _tui()
    tui._busy_mode = "steer"
    tui._turn_running.set()
    cancelled = []
    import jaeger_os.main as m
    orig = m.request_turn_cancel
    m.request_turn_cancel = lambda: cancelled.append(True)
    try:
        tui._submit_turn("text", "steer me")
    finally:
        m.request_turn_cancel = orig
    assert cancelled == [True]
    assert tui._turn_queue.get_nowait() == ("text", "steer me")


def test_busy_voice_input_coalesces_without_interrupting() -> None:
    tui = _tui()
    tui._busy_mode = "interrupt"
    tui._turn_running.set()
    cancelled = []
    import jaeger_os.main as m
    orig = m.request_turn_cancel
    m.request_turn_cancel = lambda: cancelled.append(True)
    try:
        tui._submit_turn("voice", "first phrase")
        tui._submit_turn("voice", "second phrase")
        tui._submit_turn("voice", "third phrase")
    finally:
        m.request_turn_cancel = orig

    assert cancelled == []
    source, text = tui._turn_queue.get_nowait()
    assert source == "voice"
    assert _split_coalesced_voice(text) == [
        "first phrase",
        "second phrase",
        "third phrase",
    ]
    assert tui._turn_queue.empty()


def test_busy_voice_coalescing_preserves_typed_queue() -> None:
    tui = _tui()
    tui._turn_running.set()
    tui._turn_queue.put(("text", "typed follow-up"))

    tui._submit_turn("voice", "voice one")
    tui._submit_turn("voice", "voice two")

    assert tui._turn_queue.get_nowait() == ("text", "typed follow-up")
    source, text = tui._turn_queue.get_nowait()
    assert source == "voice"
    assert _split_coalesced_voice(text) == ["voice one", "voice two"]


def test_coalesced_voice_format_round_trips() -> None:
    formatted = _format_coalesced_voice(["one", "two"])
    assert "combined turn" in formatted
    assert _split_coalesced_voice(formatted) == ["one", "two"]


# ── busy mode get/set ────────────────────────────────────────────────


def test_set_busy_mode_accepts_valid() -> None:
    tui = _tui()
    for mode in ("interrupt", "queue", "steer"):
        assert tui.set_busy_mode(mode) is True
        assert tui._busy_mode == mode


def test_set_busy_mode_rejects_unknown() -> None:
    tui = _tui()
    tui._busy_mode = "interrupt"
    assert tui.set_busy_mode("teleport") is False
    assert tui._busy_mode == "interrupt"


def test_configured_busy_mode_defaults_to_interrupt() -> None:
    # No pipeline config in a skip_model TUI → the safe default.
    assert _tui()._configured_busy_mode() == "interrupt"


# ── slash gating while a turn runs ───────────────────────────────────


def test_turn_unsafe_slash_is_refused_while_running() -> None:
    tui = _tui()
    tui._turn_running.set()
    with tui.console.capture() as cap:
        quit_ = tui._dispatch_slash("/model")
    assert quit_ is False
    assert "a turn is running" in cap.get()


def test_safe_slash_runs_while_turn_running() -> None:
    tui = _tui()
    tui._turn_running.set()
    # /help is read-only — it must still work mid-turn.
    quit_ = tui._dispatch_slash("/help")
    assert quit_ is False


def test_quit_slash_returns_true() -> None:
    assert _tui()._dispatch_slash("/quit") is True


# ── the drain helper ─────────────────────────────────────────────────


def test_drain_turn_queue_empties_it() -> None:
    tui = _tui()
    for n in range(5):
        tui._turn_queue.put(("text", str(n)))
    tui._drain_turn_queue()
    assert tui._turn_queue.empty()
