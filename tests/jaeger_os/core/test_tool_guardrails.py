"""Per-turn loop guardrail — corrective guidance before the hard backstop.

``main._run_via_iter`` already halts a spinning turn via ``_loop_halt_reason``,
but only once the loop is established and only with a message to the *user*.
``ToolGuardrail`` is the earlier, softer layer: it watches the same signals and
hands the *model* a concrete instruction the step a turn starts to spin, so it
can break the loop itself. These tests pin the three loop classes — repeated
failure, idempotent no-progress, identical-call — the warn-once behaviour, and
the ``merge_guidance`` payload merge.
"""

from __future__ import annotations

from jaeger_os.core.tool_guardrails import ToolGuardrail, merge_guidance


# ── repeated failure ─────────────────────────────────────────────────


def test_failure_warns_on_first_failure():
    """A failing call is flagged immediately so the model can recover
    before a second identical failure trips the terminal halt."""
    g = ToolGuardrail()
    warn = g.observe(
        "run_python", {"code": "x"},
        {"ok": False, "error": "bad"}, "run_python|app.py|SyntaxError",
    )
    assert warn is not None
    assert "run_python" in warn
    assert "Loop guard" in warn


def test_failure_warns_once_per_signature():
    g = ToolGuardrail()
    sig = "run_python|app.py|SyntaxError"
    first = g.observe("run_python", {"code": "x"}, {"ok": False}, sig)
    second = g.observe("run_python", {"code": "x"}, {"ok": False}, sig)
    assert first is not None
    assert second is None


def test_failure_takes_priority_over_no_progress():
    """A failing idempotent call surfaces the failure guidance, not the
    no-progress guidance."""
    g = ToolGuardrail()
    warn = g.observe(
        "file_read", {"path": "x"},
        {"read": False, "error": "not found"}, "file_read|x|not found",
    )
    assert warn is not None
    assert "failed" in warn


# ── idempotent no-progress ───────────────────────────────────────────


def test_no_progress_warns_on_second_identical_result():
    g = ToolGuardrail()
    content = {"read": True, "content": "X"}
    assert g.observe("file_read", {"path": "a"}, content) is None
    warn = g.observe("file_read", {"path": "a"}, content)
    assert warn is not None
    assert "same result" in warn


def test_no_progress_warns_once():
    g = ToolGuardrail()
    content = {"read": True, "content": "X"}
    g.observe("file_read", {"path": "a"}, content)
    assert g.observe("file_read", {"path": "a"}, content) is not None
    assert g.observe("file_read", {"path": "a"}, content) is None


def test_no_progress_resets_when_result_changes():
    """A changed result means the call IS making progress — the counter
    starts over."""
    g = ToolGuardrail()
    assert g.observe("file_read", {"path": "a"}, {"content": "X"}) is None
    assert g.observe("file_read", {"path": "a"}, {"content": "Y"}) is None
    assert g.observe("file_read", {"path": "a"}, {"content": "Y"}) is not None


# ── identical-call tight loop ────────────────────────────────────────


def test_identical_call_warns_on_second_call():
    g = ToolGuardrail()
    assert g.observe("terminal", {"cmd": "ls"}, {"ok": True}) is None
    warn = g.observe("terminal", {"cmd": "ls"}, {"ok": True})
    assert warn is not None
    assert "identical arguments" in warn


def test_identical_call_warns_once():
    g = ToolGuardrail()
    g.observe("terminal", {"cmd": "ls"}, {"ok": True})
    assert g.observe("terminal", {"cmd": "ls"}, {"ok": True}) is not None
    assert g.observe("terminal", {"cmd": "ls"}, {"ok": True}) is None


def test_non_idempotent_different_args_never_warns():
    """Varying arguments is progress — no guidance even across many calls."""
    g = ToolGuardrail()
    assert g.observe("terminal", {"cmd": "ls"}, {"ok": True}) is None
    assert g.observe("terminal", {"cmd": "pwd"}, {"ok": True}) is None
    assert g.observe("terminal", {"cmd": "date"}, {"ok": True}) is None


def test_healthy_varied_sequence_never_warns():
    g = ToolGuardrail()
    assert g.observe("get_time", {}, {"time": "1"}) is None
    assert g.observe("file_read", {"path": "a"}, {"content": "A"}) is None
    assert g.observe("calculate", {"expr": "2+2"}, {"result": 4}) is None


# ── merge_guidance ───────────────────────────────────────────────────


def test_merge_guidance_into_dict_keeps_payload():
    out = merge_guidance({"read": True, "content": "x"}, "GUIDE")
    assert out == {"read": True, "content": "x", "loop_guard": "GUIDE"}


def test_merge_guidance_does_not_mutate_the_original_dict():
    original = {"a": 1}
    merge_guidance(original, "GUIDE")
    assert "loop_guard" not in original


def test_merge_guidance_into_string_appends():
    assert merge_guidance("result text", "GUIDE") == "result text\n\nGUIDE"


def test_merge_guidance_wraps_other_types():
    assert merge_guidance(None, "GUIDE") == {"result": None, "loop_guard": "GUIDE"}
    assert merge_guidance([1, 2], "GUIDE") == {"result": [1, 2], "loop_guard": "GUIDE"}
