"""Per-turn loop guardrail — corrective feedback one step before the halt.

``main._run_via_iter`` already has a hard backstop (``_loop_halt_reason``):
it terminates a spinning turn, but only once the loop is fully established,
and its message goes to the *user*. This guardrail is the softer, earlier
layer. It watches the same signals — repeated failures, identical calls,
idempotent no-progress — and, the step a turn *starts* to spin, returns a
concrete instruction the loop appends to the tool result so the MODEL can
break the loop itself on its next move.

It never halts: the backstop still owns termination. This only ever adds a
``loop_guard`` field to a tool result. Mirrors Hermes'
``agent/tool_guardrails.py``, adapted to Jaeger's pydantic-ai node loop —
where a call cannot be blocked mid-graph, so the existing terminal halt is
kept as the block and this is purely the advisory layer.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

# Warn one step before the matching hard-stop threshold in main.py
# (``_MAX_SEMANTIC_FAILURES = 2``, ``_MAX_IDENTICAL_CALLS = 4``) so the model
# gets a real chance to recover before the turn is cut off.
_WARN_AFTER_FAILURES = 1
_WARN_AFTER_IDENTICAL = 2
_WARN_AFTER_NO_PROGRESS = 2

# Read-only / idempotent tools: re-running one with identical arguments and
# getting an identical result is spin by definition, never progress.
_IDEMPOTENT_TOOLS = frozenset({
    "file_read", "list_skill_dir", "search_files", "search_memory",
    "get_time", "system_status", "list_facts", "recall", "list_schedules",
    "list_plugins", "list_credentials", "computer_capture",
    "computer_look", "computer_windows",
})

_GUIDANCE_KEY = "loop_guard"


def call_signature(tool_name: str, args: Any) -> str:
    """A stable per-call signature — ``tool|args``. The loop backstop's
    identical-call counter and this guardrail both key calls through here, so
    the warn thresholds stay aligned with the halt thresholds by construction
    rather than by two copies of the same format string."""
    return f"{tool_name}|{args!r}"


def _result_hash(content: Any) -> str:
    """A stable digest of a tool result, for spotting identical returns."""
    try:
        blob = json.dumps(content, sort_keys=True, default=str)
    except (TypeError, ValueError):
        blob = repr(content)
    return hashlib.sha256(blob.encode("utf-8", "replace")).hexdigest()


def merge_guidance(content: Any, guidance: str) -> Any:
    """Return ``content`` with loop guidance attached, without losing the
    original payload. A dict gains a ``loop_guard`` key; a string gets the
    guidance appended; anything else is wrapped into a dict."""
    if isinstance(content, dict):
        return {**content, _GUIDANCE_KEY: guidance}
    if isinstance(content, str):
        return f"{content}\n\n{guidance}"
    return {"result": content, _GUIDANCE_KEY: guidance}


class ToolGuardrail:
    """Watches one turn's tool returns and emits guidance when it spins.

    Construct one per turn (state is per-turn and never reset in place).
    Feed every tool return through :meth:`observe`; attach any returned
    string to that tool's result.
    """

    def __init__(self) -> None:
        self._failures: dict[str, int] = {}
        self._calls: dict[str, int] = {}
        # call signature -> (last result hash, consecutive-identical count)
        self._no_progress: dict[str, tuple[str, int]] = {}
        self._warned: set[str] = set()

    def observe(
        self,
        tool_name: str,
        args: Any,
        content: Any,
        fail_sig: str | None = None,
    ) -> str | None:
        """Record one tool return; return guidance to surface to the model
        when this call is starting to spin, else ``None``.

        ``fail_sig`` is main's :func:`_semantic_failure_signature` for this
        return — non-``None`` means the call failed. At most one guidance
        string per call, and each distinct loop is flagged only once.
        """
        call_sig = call_signature(tool_name, args)

        # 1. Repeated semantic failure — highest-signal loop, warned first so
        #    the model can recover before a second failure trips the halt.
        if fail_sig:
            count = self._failures.get(fail_sig, 0) + 1
            self._failures[fail_sig] = count
            if count >= _WARN_AFTER_FAILURES and self._first(f"fail:{fail_sig}"):
                return (
                    f"⚠ Loop guard: {tool_name} just failed. Retrying it "
                    "unchanged will fail the same way and end the turn. Fix "
                    "the underlying cause, try a different tool or different "
                    "arguments, or tell the user what is blocking you."
                )

        if tool_name in _IDEMPOTENT_TOOLS:
            # 2. An idempotent tool returning an identical result — the model
            #    is re-reading instead of acting on what it already has.
            digest = _result_hash(content)
            last, repeats = self._no_progress.get(call_sig, ("", 0))
            repeats = repeats + 1 if digest == last else 1
            self._no_progress[call_sig] = (digest, repeats)
            if repeats >= _WARN_AFTER_NO_PROGRESS and self._first(f"noprog:{call_sig}"):
                return (
                    f"⚠ Loop guard: {tool_name} returned the same result "
                    f"{repeats}× in a row. Re-running it will not change "
                    "anything — act on the result you already have."
                )
        else:
            # 3. The same (tool, args) issued repeatedly — a generic tight
            #    loop on a tool whose result may legitimately vary.
            count = self._calls.get(call_sig, 0) + 1
            self._calls[call_sig] = count
            if count >= _WARN_AFTER_IDENTICAL and self._first(f"ident:{call_sig}"):
                return (
                    f"⚠ Loop guard: you have called {tool_name} with "
                    f"identical arguments {count}×. That is not making "
                    "progress — change the arguments or move to a "
                    "different step. The turn ends automatically after "
                    "repeated identical calls."
                )
        return None

    def _first(self, marker: str) -> bool:
        """True the first time a given loop marker is seen this turn."""
        if marker in self._warned:
            return False
        self._warned.add(marker)
        return True
