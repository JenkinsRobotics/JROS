"""P4 loop backstop — the turn-termination safety net.

A turn must end. ``_loop_halt_reason`` watches two failure modes of a
small model: the tight loop (the exact same tool + args issued over and
over) and the runaway (an absurd number of total calls in one turn).
Neither limit should trip on healthy multi-step work, which tops out
near ~16 varied calls.
"""

from __future__ import annotations

from types import SimpleNamespace

from jaeger_os.main import (
    _MAX_IDENTICAL_CALLS,
    _MAX_SEMANTIC_FAILURES,
    _MAX_TOOL_CALLS,
    _loop_halt_reason,
    _needs_execution_retry,
    _semantic_failure_signature,
)


# ── healthy turns do not halt ────────────────────────────────────────


def test_no_halt_on_empty_turn() -> None:
    assert _loop_halt_reason(0, {}) is None


def test_no_halt_on_short_varied_turn() -> None:
    sigs = {f"run_python|{{'code': {i}}}": 1 for i in range(8)}
    assert _loop_halt_reason(8, sigs) is None


def test_no_halt_on_legit_long_turn() -> None:
    # ~16 distinct calls is observed legitimate multi-step work.
    sigs = {f"tool_{i}|args_{i}": 1 for i in range(16)}
    assert _loop_halt_reason(16, sigs) is None


def test_no_halt_just_below_identical_cap() -> None:
    sigs = {"read_file|{'path': 'a'}": _MAX_IDENTICAL_CALLS - 1}
    assert _loop_halt_reason(_MAX_IDENTICAL_CALLS - 1, sigs) is None


# ── tight identical-call loop ────────────────────────────────────────


def test_halt_on_identical_call_loop() -> None:
    sigs = {"read_file|{'path': 'a'}": _MAX_IDENTICAL_CALLS}
    reason = _loop_halt_reason(_MAX_IDENTICAL_CALLS, sigs)
    assert reason is not None
    assert "read_file" in reason
    assert "identical" in reason


def test_halt_on_repeated_semantic_failure() -> None:
    failures = {"run_python|fib10.py|SyntaxError: invalid syntax": _MAX_SEMANTIC_FAILURES}
    reason = _loop_halt_reason(2, {}, failures)
    assert reason is not None
    assert "run_python failure" in reason


def test_semantic_failure_signature_normalizes_error() -> None:
    sig = _semantic_failure_signature(
        "run_python",
        {"path": "fib10.py"},
        {"ok": False, "stderr": "SyntaxError: invalid syntax\nmore details"},
    )
    assert sig == "run_python|fib10.py|SyntaxError: invalid syntax"


def test_plan_only_multistep_response_needs_execution_retry() -> None:
    iter_out = {
        "skipped": False,
        "first_decision": None,
        "result": SimpleNamespace(output="First, I would create the file. Then I would run it."),
    }

    assert _needs_execution_retry(iter_out, "Create a file, append a line, then read it.")


def test_explanatory_request_does_not_need_execution_retry() -> None:
    iter_out = {
        "skipped": False,
        "first_decision": None,
        "result": SimpleNamespace(output="First, install Python. Then run the script."),
    }

    assert not _needs_execution_retry(iter_out, "Explain how to create and run a Python file.")


def test_identical_loop_reports_tool_name_only() -> None:
    # The reason quotes the tool name, not the raw args blob.
    sigs = {"run_python|{'code': 'x'}": _MAX_IDENTICAL_CALLS + 2}
    reason = _loop_halt_reason(_MAX_IDENTICAL_CALLS + 2, sigs)
    assert reason is not None
    assert reason.startswith("called run_python")
    assert "'code'" not in reason


# ── runaway total-call ceiling ───────────────────────────────────────


def test_halt_on_runaway_total() -> None:
    # Many distinct calls, none repeated enough to trip the tight loop,
    # but the sheer count is a runaway.
    n = _MAX_TOOL_CALLS + 1
    sigs = {f"tool_{i}|args_{i}": 1 for i in range(n)}
    reason = _loop_halt_reason(n, sigs)
    assert reason is not None
    assert str(n) in reason
    assert "single turn" in reason


def test_no_halt_at_exactly_the_ceiling() -> None:
    # The ceiling is exclusive — exactly _MAX_TOOL_CALLS is still allowed.
    sigs = {f"tool_{i}|args_{i}": 1 for i in range(_MAX_TOOL_CALLS)}
    assert _loop_halt_reason(_MAX_TOOL_CALLS, sigs) is None


# ── precedence ───────────────────────────────────────────────────────


def test_identical_loop_checked_before_runaway() -> None:
    # Both conditions true: the tight-loop reason wins, since it is the
    # more specific, more actionable diagnosis.
    sigs = {"spin|{}": _MAX_TOOL_CALLS + 5}
    reason = _loop_halt_reason(_MAX_TOOL_CALLS + 5, sigs)
    assert reason is not None
    assert "identical" in reason


# ── limits stay sane ─────────────────────────────────────────────────


def test_limits_are_ordered_sanely() -> None:
    # A runaway must be allowed more room than a single tight loop, or
    # the ceiling would mask the more specific diagnosis.
    assert _MAX_IDENTICAL_CALLS < _MAX_TOOL_CALLS
