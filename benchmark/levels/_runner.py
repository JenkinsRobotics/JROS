"""Shared runner helpers for the tiered benchmark suite.

Boots the in-process model client once, exposes ``run_turn`` for the
per-level modules. Each turn captures: prompt, tool sequence (every
tool call the agent made, in order), the final answer text, latency,
and any error. Levels apply their own scoring on top of these rows.

The boot path is :func:`jaeger_os.main.boot_for_tui` — the same flow
the TUI uses — so latency numbers reflect a real run.
"""

from __future__ import annotations

import gc
import io
import os
import sys
import time
from contextlib import redirect_stdout
from dataclasses import dataclass, field
from typing import Any

# Resolve src/ for in-repo runs (mirrors bench.py shape).
import pathlib
_REPO = pathlib.Path(__file__).resolve().parents[2]
for _candidate in (_REPO, _REPO / "src"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))


# ── Data shapes ─────────────────────────────────────────────────────


@dataclass
class TurnRow:
    """One LLM turn's worth of observed behavior."""

    prompt: str
    answer: str
    tools_called: list[str]                 # ordered list of tool names
    tool_args: list[dict[str, Any]]         # parallel list of arg dicts
    tool_results: list[Any]                 # parallel list of raw result objects
    elapsed_s: float
    error: str | None = None
    session_key: str | None = None
    extras: dict[str, Any] = field(default_factory=dict)


# ── LLM boot ────────────────────────────────────────────────────────


def boot_jaeger_client(*, warmup: bool = True) -> Any:
    """Boot the jaeger pipeline (instance lock, model load, agent build,
    prewarm) and return a (client, cleanup) pair. The bench takes the
    client and uses it for every turn; cleanup releases the lock + LLM
    at shutdown."""
    from jaeger_os.main import boot_for_tui

    result = boot_for_tui(
        instance_name="default",
        with_memory=True,
        warmup=warmup,
    )
    return result


# ── Turn execution ──────────────────────────────────────────────────


def _walk_messages_for_calls(result: Any) -> tuple[list[str], list[dict], list[Any]]:
    """Extract (tool_names, tool_args, tool_results) from a pydantic-ai
    RunResult. Returns three parallel lists, one entry per tool-return."""
    names: list[str] = []
    args: list[dict] = []
    results: list[Any] = []
    pending: dict[str, dict[str, Any]] = {}
    try:
        msgs = list(result.all_messages()) if hasattr(result, "all_messages") else []
    except Exception:
        return names, args, results
    for msg in msgs:
        kind = getattr(msg, "kind", None)
        if kind == "response":
            for part in msg.parts:
                if getattr(part, "part_kind", None) == "tool-call":
                    pending[part.tool_call_id] = {
                        "name": part.tool_name,
                        "args": part.args if isinstance(part.args, dict) else {},
                    }
        elif kind == "request":
            for part in msg.parts:
                if getattr(part, "part_kind", None) != "tool-return":
                    continue
                call = pending.pop(getattr(part, "tool_call_id", None), None)
                if call is None:
                    name = getattr(part, "tool_name", "?")
                    names.append(name)
                    args.append({})
                else:
                    names.append(call["name"])
                    args.append(call["args"])
                results.append(getattr(part, "content", None))
    return names, args, results


def _run_turn_via_new_agent(
    client: Any,
    prompt: str,
    *,
    session_key: str,
) -> TurnRow:
    """Phase-6 bench dispatch — drive the turn through ``JaegerAgent``
    instead of pydantic-ai. Returns the same :class:`TurnRow` shape so
    the level scorers don't need to know which loop ran."""
    from jaeger_os.agent.runtime_bridge import build_jaeger_agent, drive_one_turn
    from jaeger_os.main import SKIP_FINAL_TOOLS, _get_agent, _pipeline

    # Drive ``_get_agent`` once so the tool registry is mirrored. The
    # per-session ``JaegerAgent`` cache lives here in the bench rather
    # than in ``main.py`` so per-process state stays clean across
    # different bench runs.
    if not hasattr(_run_turn_via_new_agent, "_agents"):
        _run_turn_via_new_agent._agents = {}  # type: ignore[attr-defined]
    cache: dict[str, Any] = _run_turn_via_new_agent._agents  # type: ignore[attr-defined]

    if session_key not in cache:
        _get_agent(client)  # triggers the mirror inside _get_agent
        cache[session_key] = build_jaeger_agent(
            client,
            system_prompt=_pipeline["system_prompt"],
            skip_final_tools=SKIP_FINAL_TOOLS,
        )
    jaeger_agent = cache[session_key]

    started = time.perf_counter()
    error: str | None = None
    out: dict[str, Any] = {}
    try:
        with open(os.devnull, "w") as devnull, redirect_stdout(devnull):
            out = drive_one_turn(jaeger_agent, prompt)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
    elapsed = time.perf_counter() - started

    # Walk the freshly appended messages to extract (tool, args, result)
    # triples in dispatch order.  Mirrors ``_walk_messages_for_calls``'s
    # contract on the new ``Message`` shape — see Phase-0 audit §6.
    tools: list[str] = []
    args: list[dict] = []
    results: list[Any] = []
    new_msgs = out.get("new_messages") or []
    pending: dict[str, dict[str, Any]] = {}
    for msg in new_msgs:
        if msg.get("role") == "assistant":
            for tc in (msg.get("tool_calls") or []):
                tool_args = tc.get("arguments") or {}
                pending[tc.get("id") or ""] = {
                    "name": tc.get("name") or "",
                    "args": tool_args if isinstance(tool_args, dict) else {},
                }
        elif msg.get("role") == "tool":
            call = pending.pop(msg.get("tool_call_id") or "", None)
            content = msg.get("content")
            try:
                import json
                parsed_result = json.loads(content) if isinstance(content, str) else content
            except (TypeError, ValueError):
                parsed_result = content
            if call is None:
                tools.append(msg.get("name") or "?")
                args.append({})
            else:
                tools.append(call["name"])
                args.append(call["args"])
            results.append(parsed_result)

    return TurnRow(
        prompt=prompt,
        answer=out.get("answer", "") or "",
        tools_called=tools,
        tool_args=args,
        tool_results=results,
        elapsed_s=elapsed,
        error=error,
        session_key=session_key,
        extras={
            "framework_path": "jaeger_os_agent",
            "iterations": out.get("iterations"),
            "halt_reason": out.get("halt_reason"),
            "skipped_final": out.get("skipped"),
        },
    )


def run_turn(
    client: Any,
    prompt: str,
    *,
    session_key: str = "bench_session",
) -> TurnRow:
    """Execute one user turn through ``jaeger_os.main.run_command``
    and capture observed tool sequence + answer + latency.

    Uses ``session_key`` to carry conversation history across turns
    (Level 3 multi-turn relies on this; Level 1/2 use unique keys per
    prompt so turns don't pollute each other).

    Phase-6.2 cutover: every turn now drives the framework-free
    :class:`JaegerAgent` loop. The returned :class:`TurnRow` shape is
    identical to what the legacy pydantic-ai path produced so level
    scorers don't need to know which loop ran."""
    return _run_turn_via_new_agent(client, prompt, session_key=session_key)

    # Below: the legacy pydantic-ai dispatch is unreachable post-6.2 and
    # gets deleted in the next cleanup pass alongside ``_run_via_iter``
    # in ``main.py``. Kept here only because ``_walk_messages_for_calls``
    # is exported for any out-of-tree caller that still needs it.
    from jaeger_os.main import (
        _format_tool_result_as_answer,
        _get_agent,
        _pipeline,
        _run_with_fix_loop,
    )
    import asyncio

    agent = _get_agent(client)
    history = None
    if _pipeline.get("with_memory"):
        from jaeger_os.main import _get_session_history
        history = _get_session_history(session_key)

    started = time.perf_counter()
    error: str | None = None
    iter_out: dict[str, Any] = {}
    try:
        # Redirect to /dev/null (NOT StringIO — see bench/lilith/bench.py
        # for the llama_decode -3 explanation).
        with open(os.devnull, "w") as devnull, redirect_stdout(devnull):
            iter_out = asyncio.run(_run_with_fix_loop(agent, prompt, history, client=client))
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"

    elapsed = time.perf_counter() - started

    answer = ""
    tools: list[str] = []
    args: list[dict] = []
    results: list[Any] = []

    if iter_out.get("skipped"):
        answer = iter_out.get("skipped_text") or ""
        fd = iter_out.get("first_decision") or {}
        if fd.get("tool"):
            tools.append(fd["tool"])
            args.append(fd.get("args") if isinstance(fd.get("args"), dict) else {})
            results.append(iter_out.get("skipped_result"))
    else:
        result_obj = iter_out.get("result")
        if result_obj is not None:
            answer = str(getattr(result_obj, "output", "") or "")
            tools, args, results = _walk_messages_for_calls(result_obj)

    # Mirror what run_command does so multi-turn scenarios see prior turns.
    if _pipeline.get("with_memory") and history is not None and iter_out:
        if iter_out.get("skipped"):
            history.extend(iter_out.get("skipped_msgs") or [])
        else:
            result_obj = iter_out.get("result")
            if result_obj is not None:
                try:
                    msgs = result_obj.new_messages() if hasattr(result_obj, "new_messages") \
                        else result_obj.all_messages()
                    history.extend(msgs)
                except Exception:
                    pass

    return TurnRow(
        prompt=prompt,
        answer=answer,
        tools_called=tools,
        tool_args=args,
        tool_results=results,
        elapsed_s=elapsed,
        error=error,
        session_key=session_key,
    )


# ── Assertion helpers (shared by all levels) ────────────────────────


def matches_tool_set(
    observed: list[str], expected: list[str], *, ordered: bool = False,
) -> bool:
    """Did the agent call every expected tool?

    ``ordered=False`` (default): set membership — every expected tool
    must appear in the observed sequence, extras are OK.
    ``ordered=True``: the observed sequence must contain expected as a
    contiguous subsequence in order.
    """
    if not expected:
        return True
    if ordered:
        # Check expected is a subsequence (not necessarily contiguous).
        it = iter(observed)
        return all(any(tool == want for tool in it) for want in expected)
    needed = list(expected)
    for tool in observed:
        if tool in needed:
            needed.remove(tool)
    return not needed


def answer_contains_any(answer: str, needles: list[str]) -> bool:
    """Case-insensitive substring check against a list of acceptable
    answer fragments. Empty needles ⇒ trivially true."""
    if not needles:
        return True
    lower = (answer or "").lower()
    return any(n.lower() in lower for n in needles)


def answer_contains_all(answer: str, needles: list[str]) -> bool:
    if not needles:
        return True
    lower = (answer or "").lower()
    return all(n.lower() in lower for n in needles)


# ── Markdown rendering helpers ──────────────────────────────────────


def md_table(headers: list[str], rows: list[list[str]]) -> str:
    """Render a simple markdown table. Caller is responsible for
    pre-escaping any pipe characters in cells."""
    if not rows:
        return ""
    out = ["| " + " | ".join(headers) + " |",
           "|" + "|".join(["---"] * len(headers)) + "|"]
    for r in rows:
        out.append("| " + " | ".join(r) + " |")
    return "\n".join(out)


def short(text: str, n: int = 60) -> str:
    text = (text or "").replace("\n", " ").replace("|", "\\|").strip()
    return text if len(text) <= n else text[: n - 1] + "…"
