#!/usr/bin/env python3
"""Jaeger CLI — self-improving local agent.

Lifecycle, in order:

  1. Resolve the instance dir (JAEGER_INSTANCE_DIR / ~/.jaeger/<name>/).
  2. Run the setup wizard if no valid instance is on disk.
  3. Take the exclusive lockfile (refuses to start if another copy holds it).
  4. Verify manifest.json's core_version matches; refuse-to-start if not.
  5. Bind tools + memory to the instance layout.
  6. Load the in-process Gemma model.
  7. Build the PydanticAI agent with the v2 system prompt + identity.
  8. Register built-in tools, then run the skill loader (base + instance
     skills, with smoke-test gating + instance-wins-over-core resolution).
  9. Enter the chat loop (slash commands + multiline paste detection).

This file is intentionally self-contained — no imports from `memory/`,
`messaging/`, or any other framework dir. Only third-party libraries and
sibling modules under `jaeger_os/`.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import select
import sys
import threading
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from pydantic_ai import Agent, CallToolsNode, ModelRequestNode
from pydantic_ai.messages import (
    ModelRequest,
    ModelResponse,
    TextPart,
    ToolReturnPart,
    UserPromptPart,
)
from pydantic_ai.usage import RequestUsage

from .core import credentials as creds
from .core import log_rotation
from .core import memory as mem
from .core import prompts as prompt_module
from .core import tools as jaeger_tools
from .core.cron_runner import CronRunner
from .core.instance import (
    CoreVersionMismatch,
    InstanceLayout,
    InstanceLock,
    check_manifest,
    default_instance_name,
    resolve_instance_dir,
    touch_manifest_started,
)
from .core.llm_model import LlamaCppModel
from .core.permissions import (
    ConsoleConfirmationProvider,
    PermissionPolicy,
    PermissionTier,
    install_policy,
    requires_tier,
)
from .core.schemas import CORE_VERSION, Config
from .core.schemas import load_yaml
from .core.skill_loader import load_and_register
from .core.setup_wizard import run_wizard


# ---------------------------------------------------------------------------
# Tools whose dict result IS the answer (skip the final-LLM round-trip).
# ---------------------------------------------------------------------------
SKIP_FINAL_TOOLS = frozenset({
    # NB historical name. These tools are "FAST_FINALIZE" — the agent.iter
    # loop is short-circuited after the FIRST tool call returns, then a
    # single bounded ``client.chat`` finalize pass (max_tokens=120,
    # temp=0.2) turns the tool result into a one-sentence user answer.
    # The LLM stays IN the pipeline (so the answer is conversational and
    # follow-up context is consistent), but the second-pass cost is
    # capped so latency stays close to the prior bypass model.
    "get_time", "calculate", "system_status",
    "list_facts", "recall", "remember", "forget",
    # NB: read_file is INTENTIONALLY not skip-final. A read is almost
    # never a terminal action — it's usually step 1 of "read then act"
    # (read a file, then finish/fix/rewrite it). Skip-final cut the loop
    # off after the read, so "finish the code" turns never reached
    # write_file. Reads now run the full agent.iter loop so the model
    # can chain into the write.
    "write_file", "append_file", "patch", "delete_file", "list_skill_dir",
    "clarify",
    "schedule_prompt", "cancel_schedule",
    "help_me",
    "list_credentials",
    "reload_skills",
    # Parity ports from pydantic_ai — same skip-final rationale: their
    # dict result IS the user-facing answer.
    "text_to_speech",
    "open_on_host",
    "delegate_task",
    "send_message",
    # get_weather: the result IS a single ready-to-show sentence
    # ("Sunny, 83°F in Downey, CA") — fast-finalize still adds a
    # conversational shape ("It's currently sunny and 83 in Downey").
    # NOTE: web_search is INTENTIONALLY not skip-final — its result is
    # a list of 5+ sources the model digests through the FULL agent
    # iter loop (not the bounded fast-finalize) so it can pick the most
    # relevant fact + cite.
    "get_weather",
    # Plugin awareness — output is structured/listy, the formatter
    # renders a clean per-plugin status report; no value in a second
    # LLM round paraphrasing it.
    "list_plugins",
    "setup_plugin",
    # Audio input — the transcript IS the user's spoken answer; the
    # model surfaces it directly so the user sees what was heard.
    "listen",
    # Kanban board mutations — quick local bookkeeping; the dict result
    # IS the answer. board_view is NOT skip-final — its card list is
    # digested through the full loop so the model can act on the board.
    "board_add", "board_move", "board_update",
})


def _format_tool_result_as_answer(name: str, result: Any) -> str:
    """Render a tool result dict into a one-line plain string."""
    if not isinstance(result, dict):
        return str(result)
    if name == "get_time":
        return result.get("datetime") or "Time unavailable."
    if name == "calculate":
        if result.get("error"):
            expr = result.get("expression", "expression")
            return f"Couldn't calculate {expr!r}: {result['error']}"
        v = result.get("result")
        return str(v) if v is not None else "Calculation failed."
    if name == "system_status":
        disk = result.get("disk") or {}
        if disk:
            return (f"disk {disk.get('used_gb', 0):.1f}/{disk.get('total_gb', 0):.1f} GB "
                    f"({disk.get('free_gb', 0):.1f} GB free)")
        return "System status unavailable."
    if name == "list_facts":
        facts = result.get("facts") or {}
        if not facts:
            return "No facts saved yet."
        return "; ".join(f"{k}: {v}" for k, v in facts.items())
    if name == "recall":
        return str(result.get("value", "")) if result.get("found") else f"No value for {result.get('key')!r}."
    if name == "remember":
        return (f"Got it — remembered {result.get('key')!r}." if result.get("remembered")
                else "Couldn't save that.")
    if name == "forget":
        return (f"Forgot {result.get('key')!r}." if result.get("forgotten")
                else f"No saved value under {result.get('key')!r}.")
    if name == "write_file":
        if not result.get("written"):
            return f"Couldn't write: {result.get('error')}"
        commit = result.get("commit")
        commit_suffix = f" [git {commit}]" if commit else ""
        base = f"Wrote {result.get('path')} ({result.get('bytes')} bytes).{commit_suffix}"
        # Phase-2 auto-syntax-check feedback (only present for .py files).
        if result.get("syntax_ok") is False:
            return f"{base}\nSYNTAX ERROR: {result.get('syntax_error')}"
        return base
    if name == "append_file":
        if not result.get("appended"):
            return f"Couldn't append: {result.get('error')}"
        commit = result.get("commit")
        commit_suffix = f" [git {commit}]" if commit else ""
        base = f"Appended {result.get('bytes')} bytes to {result.get('path')}.{commit_suffix}"
        if result.get("syntax_ok") is False:
            return f"{base}\nSYNTAX ERROR: {result.get('syntax_error')}"
        return base
    if name == "patch":
        if not result.get("edited"):
            return f"Couldn't edit: {result.get('error')}"
        commit = result.get("commit")
        commit_suffix = f" [git {commit}]" if commit else ""
        reps = result.get("replacements", 1)
        base = f"Edited {result.get('path')} ({reps} replacement{'s' if reps != 1 else ''}).{commit_suffix}"
        if result.get("syntax_ok") is False:
            return f"{base}\nSYNTAX ERROR: {result.get('syntax_error')}"
        return base
    if name == "delete_file":
        if not result.get("deleted"):
            return f"Couldn't delete: {result.get('reason') or result.get('error')}"
        commit = result.get("commit")
        suffix = f" [git {commit}]" if commit else ""
        return f"Deleted {result.get('path')}.{suffix}"
    if name == "read_file":
        return (result.get("content") or "")[:8000] if result.get("read") else f"Couldn't read: {result.get('error')}"
    if name == "list_skill_dir":
        if not result.get("listed"):
            return f"Couldn't list: {result.get('error')}"
        entries = result.get("entries") or []
        if not entries:
            return f"{result.get('path')}/ is empty."
        return "\n".join(f"  {e['type'][0]} {e['name']}" for e in entries)
    if name == "clarify":
        return str(result.get("question") or "")
    if name == "schedule_prompt":
        return (f"Scheduled {result.get('name')!r} — next run at {result.get('next_run_at')!r}."
                if result.get("scheduled") else f"Couldn't schedule: {result.get('error')}")
    if name == "cancel_schedule":
        return (f"Cancelled {result.get('name')!r}." if result.get("cancelled")
                else f"No schedule {result.get('name')!r}.")
    if name == "help_me":
        return result.get("summary") or ""
    if name == "list_credentials":
        names = result.get("credentials") or []
        return ("Credentials: " + ", ".join(names)) if names else "No credentials stored yet."
    if name == "reload_skills":
        newly = result.get("newly_registered") or []
        skipped = result.get("skipped") or []
        bits = []
        if newly:
            bits.append("Registered: " + ", ".join(f"{s['name']}_v{s['version']}" for s in newly))
        else:
            bits.append("No new skills to register.")
        if skipped:
            bits.append("Skipped: " + ", ".join(
                f"{s['name']}_v{s['version']} ({s['reason'][:60]})" for s in skipped
            ))
        return " ".join(bits)
    if name == "text_to_speech":
        if result.get("spoken") is True:
            # Echo the spoken line so a CLI turn isn't a bare tool entry
            # with no answer. Shown verbatim — _fast_finalize passes
            # text_to_speech through without an LLM rephrase.
            spoken = (result.get("text") or "").strip()
            return f"🔊 {spoken}" if spoken else "Spoken aloud."
        return f"Couldn't speak: {result.get('reason', 'unknown')}"
    if name == "open_on_host":
        if result.get("opened"):
            what = result.get("url") or result.get("path") or result.get("app") or ""
            return f"Opened {what}."
        return f"Couldn't open: {result.get('error', 'unknown')}"
    if name == "delegate_task":
        if result.get("delegated"):
            return str(result.get("answer") or "")
        return f"Delegation failed: {result.get('error', 'unknown')}"
    if name == "send_message":
        if result.get("sent"):
            return "Sent."
        return f"Couldn't send: {result.get('error', 'unknown')}"
    if name == "web_search":
        if result.get("error"):
            tried = result.get("tried") or []
            tail = ("\n  tried: " + "; ".join(tried)) if tried else ""
            return f"Search failed: {result['error']}{tail}"
        results = result.get("results") or []
        if not results:
            return f"No results for {result.get('query', '')!r}."
        lines = []
        for r in results[:5]:
            title = (r.get("title") or "").strip()
            url = (r.get("url") or "").strip()
            snippet = (r.get("snippet") or "").strip()
            if len(snippet) > 200:
                snippet = snippet[:200].rstrip() + "…"
            lines.append(f"• {title}\n  {url}\n  {snippet}")
        backend = result.get("backend")
        # Only call out the backend when it's NOT the preferred one —
        # users don't need to know "ddgs served you" on every search,
        # but they DO want to know "this came from Wikipedia fallback".
        if backend and backend != "ddgs":
            lines.append(f"\n[via {backend} fallback]")
        return "\n".join(lines)
    if name == "get_weather":
        if result.get("error"):
            return f"Weather lookup failed: {result['error']}"
        weather = result.get("weather") or ""
        location = result.get("location") or ""
        return f"{location}: {weather}" if location else weather or "Weather unavailable."
    if name == "list_plugins":
        if result.get("error"):
            return f"Plugins unavailable: {result['error']}"
        plugins = result.get("plugins") or []
        if not plugins:
            return "No plugins found."
        lines = []
        for p in plugins:
            status = p.get("status", "unknown")
            desc = (p.get("description") or "").split("\n")[0]
            lines.append(f"• {p['name']} — {status}: {desc}")
        return "\n".join(lines)
    if name == "setup_plugin":
        if result.get("error"):
            return f"Setup unavailable: {result['error']}"
        plugin = result.get("plugin") or "(unknown)"
        steps = result.get("steps") or []
        header = f"Setup for {plugin}:"
        return header + "\n" + "\n".join(f"  {i+1}. {s}" for i, s in enumerate(steps))
    if name == "listen":
        if not result.get("ok"):
            return f"Couldn't listen: {result.get('error', 'unknown')}"
        text = (result.get("transcript") or "").strip()
        if not text:
            return f"(no speech detected in {result.get('seconds')}s)"
        return f"Heard: {text}"
    if name == "board_add":
        if not result.get("ok"):
            return f"Couldn't add card: {result.get('error', 'unknown')}"
        return f"Added card {result.get('card_id')} — {result.get('title')!r} → {result.get('column')}."
    if name == "board_move":
        if not result.get("ok"):
            return f"Couldn't move card: {result.get('error', 'unknown')}"
        return f"Moved {result.get('card_id')} → {result.get('column')}."
    if name == "board_update":
        if not result.get("ok"):
            return f"Couldn't update card: {result.get('error', 'unknown')}"
        return f"Updated {result.get('card_id')} ({', '.join(result.get('updated') or [])})."
    return str(result)


# ---------------------------------------------------------------------------
# Pipeline state
# ---------------------------------------------------------------------------
_DEFAULT_SESSION_KEY = "cli"
_MAX_HISTORY_MESSAGES = 20

_pipeline: dict[str, Any] = {
    "layout": None,
    "config": None,
    "system_prompt": "",
    "llm_lock": None,
    "show_latency": False,
    "show_tool_activity": True,
    "show_help_on_start": True,
    # Whether the KV cache has been primed with the system prompt + tool
    # schema (set by `prewarm`). Once True, the first user-facing turn
    # skips its cold-cache prefill penalty. Mirrors python_pydantic_ai.
    "prewarmed": False,
    # When False (default), every prompt runs with a fresh context — no
    # prior turns are loaded from the episodic log, no in-process history
    # is accumulated across turns. Mirrors python_pydantic_ai, which
    # gates the same path behind --with-memory. Routing benchmarks need
    # this OFF: by prompt 23, an accumulated history of 22 turns dilutes
    # the MANDATORY rules at the top of the system prompt enough to
    # cost ~3/23 on Gemma 4.
    "with_memory": False,
    # MCP (Model Context Protocol) bridge — when on, jaeger connects to
    # configured MCP servers at startup and re-exports their tools through
    # the same agent surface. Each server's tools are registered dynamically
    # from their JSON Schema, so adding a server takes no code change.
    "with_mcp": False,
    "mcp_specs": [],
    # Background ThinkingRunner — fires a chain-of-thought call after each
    # user turn on a single-worker pool, sharing the same LLM lock so it
    # never decodes against the main loop. Logs to plugins/thinking.jsonl.
    "with_thinking": False,
    "thinking_runner": None,
    # The active llama-cpp client (set by init_extensions). Plugins reach
    # back through this when they need to issue their own LLM calls.
    "client": None,
    # OpenAI-format tool schemas from the most recent decide call.
    # _fast_finalize passes these to its bounded chat call so it renders
    # the SAME <system + tools> prompt prefix — without it the finalize
    # evicts the tool-schema KV and every following turn cold-prefills
    # ~60 schemas (the ~12s/turn regression).
    "openai_tools": None,
    # /goal — session-scoped completion condition. When set, the TUI
    # REPL runs an evaluator after each turn; if the goal isn't met,
    # it auto-fires the next turn with the evaluator's reason as the
    # prompt. Mirrors Claude Code's /goal (see code.claude.com/docs/en/goal).
    "goal": None,  # GoalState | None
}

_session_histories: dict[str, list[Any]] = {}
_session_loaded: set[str] = set()


# ---------------------------------------------------------------------------
# /goal — autonomous completion condition (Claude-Code-style)
#
# Set via slash command in the TUI. Each goal carries: the condition
# text, a turn counter, token-spend counter, started_at timestamp, the
# most recent evaluator reason, and a hard iteration cap so a misjudged
# goal can't loop forever.
# ---------------------------------------------------------------------------
@dataclass
class GoalState:
    condition: str
    started_at: float = field(default_factory=time.time)
    turns_evaluated: int = 0
    tokens_spent: int = 0
    last_reason: str = ""
    max_iterations: int = 20            # hard cap mirroring Claude's default
    achieved: bool = False              # set True when eval returns "yes"
    achieved_at: float | None = None

    def elapsed_s(self) -> float:
        return time.time() - self.started_at


def get_goal() -> "GoalState | None":
    """Return the active GoalState, or None when no goal is set."""
    return _pipeline.get("goal")


def set_goal(condition: str, *, max_iterations: int = 20) -> "GoalState":
    """Install a new goal, replacing any previously-active one."""
    g = GoalState(condition=condition.strip(), max_iterations=max_iterations)
    _pipeline["goal"] = g
    return g


def clear_goal() -> "GoalState | None":
    """Remove the active goal. Returns whatever was there (for logging)."""
    prior = _pipeline.get("goal")
    _pipeline["goal"] = None
    return prior


_GOAL_EVAL_DIRECTIVE = (
    "You are evaluating whether a session goal has been achieved. The goal:\n"
    "---\n{condition}\n---\n\n"
    "Look at the conversation transcript so far. The assistant has been "
    "working toward the goal. Decide:\n"
    "  * MET   — the condition is now satisfied based on what the assistant "
    "has surfaced in the transcript (tool results, files written, "
    "explanations given).\n"
    "  * NOT MET — the condition is not yet satisfied. Give a SHORT (one "
    "sentence) reason explaining what is still missing or what the "
    "assistant should do next.\n\n"
    "Reply with exactly one of these formats, nothing else:\n"
    "  MET: <one sentence summary of why the goal is satisfied>\n"
    "  NOT MET: <one sentence on what's still needed>"
)


def evaluate_goal(
    client: Any,
    goal: "GoalState",
    transcript_tail: str,
) -> tuple[bool, str]:
    """Run the goal evaluator. Returns ``(met, reason)``.

    Uses a bounded ``client.chat`` call (max_tokens=120, temp=0) so the
    per-turn evaluation cost stays small — same pattern as
    ``_fast_finalize_sync``. Falls back to (False, error) on any model
    failure so the caller can decide to stop the loop."""
    directive = _GOAL_EVAL_DIRECTIVE.format(condition=goal.condition)
    try:
        result = client.chat(
            [
                {"role": "system",
                 "content": "You are a precise goal evaluator. Reply in "
                            "the exact MET/NOT MET format requested."},
                {"role": "user",
                 "content": f"Conversation tail:\n{transcript_tail[-4000:]}"},
                {"role": "user", "content": directive},
            ],
            max_tokens=120,
            temperature=0.0,
            top_p=0.9,
            stream=False,
        )
        text = (getattr(result, "text", None) or "").strip()
    except Exception as exc:  # noqa: BLE001
        return False, f"evaluator error: {exc}"

    upper = text.upper()
    if upper.startswith("MET:") or upper.startswith("MET ") or upper == "MET":
        reason = text.split(":", 1)[1].strip() if ":" in text else text
        return True, reason
    if upper.startswith("NOT MET"):
        reason = text.split(":", 1)[1].strip() if ":" in text else text
        return False, reason
    # Ambiguous output: assume not met and surface the raw text as reason.
    return False, f"(ambiguous eval output) {text[:200]}"


@dataclass
class LatencyReport:
    total: float
    tool_calls: int
    decision: float
    decision_ttft: float
    tool: float
    final: float
    final_ttft: float


def print_latency(report: LatencyReport) -> None:
    print("Latency:")
    print(f"- decision: {report.decision:.3f}s  (ttft {report.decision_ttft:.3f}s)")
    print(f"- tool: {report.tool:.3f}s")
    print(f"- final: {report.final:.3f}s  (ttft {report.final_ttft:.3f}s)")
    print(f"- total: {report.total:.3f}s  (tool_calls: {report.tool_calls})")


def write_log(entry: dict[str, Any]) -> None:
    layout: InstanceLayout = _pipeline["layout"]
    layout.logs_dir.mkdir(parents=True, exist_ok=True)
    entry = {
        "framework": "jaeger_os",
        "core_version": CORE_VERSION,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        **entry,
    }
    with layout.latency_log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=True, default=str) + "\n")
    if _pipeline["with_memory"]:
        _record_episodic(entry)


def _record_episodic(entry: dict[str, Any]) -> None:
    user = entry.get("user")
    if not user:
        return
    try:
        mem.append_episodic({
            "timestamp": entry.get("timestamp"),
            "framework": "jaeger_os",
            "session_key": entry.get("session_key"),
            "user": user,
            "decision_raw": json.dumps(entry.get("decision"), ensure_ascii=True, default=str)
                if entry.get("decision") is not None else None,
            "answer": entry.get("answer"),
        })
    except Exception as exc:
        print(f"[jaeger] episodic append failed: {exc}", file=sys.stderr, flush=True)


# ---------------------------------------------------------------------------
# Per-session conversation history
# ---------------------------------------------------------------------------
def _episodic_to_messages(turns: list[dict[str, str]]) -> list[Any]:
    out: list[Any] = []
    pending_user: str | None = None
    for entry in turns:
        role = entry.get("role")
        content = entry.get("content")
        if not isinstance(content, str):
            continue
        if role == "user":
            pending_user = content
        elif role == "assistant" and pending_user is not None:
            out.append(ModelRequest(parts=[UserPromptPart(content=pending_user)]))
            out.append(ModelResponse(
                parts=[TextPart(content=content)],
                usage=RequestUsage(input_tokens=0, output_tokens=0),
                model_name="local-gemma-4-26b-a4b",
                timestamp=datetime.now(timezone.utc),
            ))
            pending_user = None
    return out


def _get_session_history(session_key: str) -> list[Any]:
    history = _session_histories.get(session_key)
    if history is None:
        history = []
        _session_histories[session_key] = history
    if session_key not in _session_loaded:
        _session_loaded.add(session_key)
        try:
            recent = mem.load_recent_turns(n=5, session_key=session_key)
            if recent:
                history.extend(_episodic_to_messages(recent))
                print(f"[jaeger] resumed {session_key!r}: {len(recent)//2} prior turn(s).", flush=True)
        except Exception as exc:
            print(f"[jaeger] resume for {session_key!r} skipped: {exc}", file=sys.stderr, flush=True)
    return history


# ---------------------------------------------------------------------------
# Agent construction
# ---------------------------------------------------------------------------
def _register_builtins(agent: Agent[None, str], client: Any) -> None:
    """Wire all the built-in Jaeger tools onto the agent.

    Skill-loader-managed skills come AFTER this — instance skills can
    override built-ins by registering a higher version of the same name.
    """
    t = jaeger_tools

    @agent.tool_plain
    @requires_tier(PermissionTier.READ_ONLY, skill="time", operation="get_time",
                   summary="read the current time")
    def get_time(timezone: str | None = None) -> dict:
        """The current date, day of the week, year, and time — the ONLY
        source of truth for "what day/date/year/time is it", "what's
        today", and similar. Your training data is frozen in the past, so
        a date or year answered from memory will be WRONG — always call
        this for anything about the present moment. Optional IANA
        timezone (e.g. 'Asia/Shanghai')."""
        return t.get_time(timezone=timezone)

    @agent.tool_plain
    @requires_tier(PermissionTier.READ_ONLY, skill="math", operation="calculate",
                   summary="evaluate an arithmetic expression")
    def calculate(expression: str) -> dict:
        """Evaluate a safe arithmetic expression. Supports + - * / ** % //
        and single-arg sqrt/abs/log/log10/exp/sin/cos/tan/floor/ceil/round.
        For "square root of N" call calculate("sqrt(N)")."""
        return t.calculate(expression=expression)

    @agent.tool_plain
    @requires_tier(PermissionTier.READ_ONLY, skill="host", operation="system_status",
                   summary="read machine + instance dir status")
    def system_status() -> dict:
        """Machine + instance dir status."""
        return t.system_status()

    @agent.tool_plain
    def write_file(path: str, content: str) -> dict:
        """Write a text file in the sandboxed skills/ directory. Overwrites
        if it already exists."""
        return t.file_write(path=path, content=content)

    @agent.tool_plain
    def append_file(path: str, content: str) -> dict:
        """Append text to an existing skills/ file."""
        return t.append_file(path=path, content=content)

    @agent.tool_plain
    def patch(path: str, old: str, new: str, replace_all: bool = False) -> dict:
        """Surgically edit an EXISTING skills/ file by find-and-replace.
        Prefer this over write_file to change a file you've already
        written — it swaps one region instead of regenerating the whole
        file, so a long file can't be lost to a truncated rewrite. `old`
        must be a snippet that occurs exactly once (pass a longer unique
        snippet if it isn't), or set replace_all=true to change every
        occurrence."""
        return t.edit_file(path=path, old=old, new=new, replace_all=replace_all)

    @agent.tool_plain
    def delete_file(path: str) -> dict:
        """Delete a file from the skills/ directory."""
        return t.delete_file(path=path)

    @agent.tool_plain
    @requires_tier(PermissionTier.READ_ONLY, skill="files", operation="read_file",
                   summary="read a workspace file")
    def read_file(path: str, offset: int = 0, limit: int | None = None) -> dict:
        """Read a text file from anywhere inside the instance dir except
        credentials/. For a large file, page it: `offset` is the 0-based
        first line, `limit` the line count (default: the whole file)."""
        return t.file_read(path=path, offset=offset, limit=limit)

    @agent.tool_plain
    @requires_tier(PermissionTier.READ_ONLY, skill="files", operation="list_skill_dir",
                   summary="list contents of the skills directory")
    def list_skill_dir(path: str = ".") -> dict:
        """List the contents of skills/ (or a subdirectory under it)."""
        return t.list_skill_dir(path=path)

    @agent.tool_plain
    @requires_tier(PermissionTier.READ_ONLY, skill="files", operation="search_files",
                   summary="search file contents under the skills directory")
    def search_files(query: str, path: str = ".", max_results: int = 50) -> dict:
        """Recursively grep file CONTENTS under skills/ — case-insensitive
        substring match. Use this to find where something is defined or
        used instead of reading files one by one. Returns {file, line,
        text} matches."""
        return t.search_files(query=query, path=path, max_results=max_results)

    @agent.tool_plain
    def remember(key: str, value: str) -> dict:
        """MANDATORY when the user states a preference, identity fact,
        plan, or anything they might recall later. Call this proactively
        — do not just acknowledge "OK, I'll remember" in text. Pick a
        descriptive snake_case key. Examples of inputs that require this
        tool: "remember that my favorite color is teal", "I drive a
        Mazda", "my name is Sam", "I'll be in Tokyo next week"."""
        return t.remember(key=key, value=value)

    @agent.tool_plain
    @requires_tier(PermissionTier.READ_ONLY, skill="memory", operation="recall",
                   summary="recall a fact by key")
    def recall(key: str) -> dict:
        """MANDATORY when the user asks about something they told you
        earlier ("what did I say my…", "do you remember…", "what's my
        favorite X", "what video length do I prefer?"). Call BEFORE
        answering — the persisted store is the source of truth.
        Fuzzy match supported, so close-but-not-exact keys still hit."""
        return t.recall(key=key)

    @agent.tool_plain
    def forget(key: str) -> dict:
        """MANDATORY when the user asks to remove a stored fact
        ("forget my X", "remove my X preference", "I changed my mind
        about X"). Call this — don't just acknowledge in text."""
        return t.forget(key=key)

    @agent.tool_plain
    @requires_tier(PermissionTier.READ_ONLY, skill="memory", operation="list_facts",
                   summary="list every stored fact")
    def list_facts() -> dict:
        """MANDATORY for open-ended "what do you know about me?" or
        "what have I told you?" questions. Returns the full k/v store.
        Use this before falling back to free-text 'I don't know'."""
        return t.list_facts()

    @agent.tool_plain
    def schedule_prompt(cron_expr: str, prompt: str, name: str | None = None) -> dict:
        """Schedule a prompt for unattended execution on a cron expression."""
        return t.schedule_prompt(cron_expr=cron_expr, prompt=prompt, name=name)

    @agent.tool_plain
    def list_schedules() -> dict:
        """List every active scheduled prompt."""
        return t.list_schedules()

    @agent.tool_plain
    def cancel_schedule(name: str) -> dict:
        """Cancel a previously-scheduled prompt by name."""
        return t.cancel_schedule(name=name)

    @agent.tool_plain
    def web_search(query: str, max_results: int = 5) -> dict:
        """Web search (multi-backend, no API key). Returns titles + URLs
        + snippets. Use this to FIND relevant pages, then web_extract to
        actually READ one."""
        return t.web_search(query=query, max_results=max_results)

    @agent.tool_plain
    def web_extract(url: str, max_chars: int = 8000) -> dict:
        """Fetch a web page and return its readable text. This is the
        research tool — web_search finds which pages matter, web_extract
        reads one. Use it to pull library docs, API references, Stack
        Overflow answers, READMEs — anything you need to understand
        before writing code for an unfamiliar task."""
        return t.web_fetch(url=url, max_chars=max_chars)

    @agent.tool_plain
    def get_weather(location: str) -> dict:
        """Look up current weather via wttr.in (no API key)."""
        return t.get_weather(location=location)

    @agent.tool_plain
    def run_python(code: str, timeout_s: float = 10.0) -> dict:
        """Execute Python in a sandboxed subprocess (10s default timeout).
        Isolated (`python -I`) — does NOT see packages installed via
        install_package. For code that needs installed libraries, use
        run_in_venv instead."""
        return t.run_python(code=code, timeout_s=timeout_s)

    @agent.tool_plain
    def terminal(command: str, timeout_s: float = 60.0) -> dict:
        """LAST RESORT — non-Python CLI tools ONLY (git, npm, brew,
        ffmpeg). NEVER use this to run Python code — that is run_python
        (stdlib) or run_in_venv (with installed packages). NEVER use it
        for file operations — that is write_file / read_file /
        list_skill_dir. It is PRIVILEGED-tier: every call interrupts the
        user for confirmation. Picking terminal when run_python or a
        file tool would do is a mistake — reach for it only when the
        task genuinely needs a non-Python command-line program."""
        return t.run_shell(command=command, timeout_s=timeout_s)

    @agent.tool_plain
    def install_package(package: str) -> dict:
        """Install a third-party Python package into this instance's
        own venv (isolated from the framework). Use when a skill you're
        building needs a library — e.g. `discord.py` for a Discord
        integration. PRIVILEGED tier: routes through the confirmation
        flow. After installing, use run_in_venv (not run_python) to run
        code that imports it."""
        return t.install_package(package=package)

    @agent.tool_plain
    def list_venv_packages() -> dict:
        """List packages installed in this instance's venv. Read-only —
        check here before install_package to see if a dependency is
        already available."""
        return t.list_venv_packages()

    @agent.tool_plain
    def run_in_venv(code: str, timeout_s: float = 30.0) -> dict:
        """Execute Python against this instance's venv interpreter so
        packages installed via install_package ARE importable. Sandboxed
        cwd, 30s default timeout (max 300s). Use this — not run_python —
        for code that depends on installed libraries."""
        return t.run_in_venv(code=code, timeout_s=timeout_s)

    @agent.tool_plain
    def list_models() -> dict:
        """List the LLM models in the registry with role (realtime /
        coder) and cache status. Read-only — use this to tell the user
        what's available, or to back a model recommendation."""
        return t.list_models()

    @agent.tool_plain
    def download_model(name: str) -> dict:
        """Download a registered model from HuggingFace Hub. PRIVILEGED
        tier — routes through confirmation. Only call this when the user
        has explicitly asked for a model OR agreed to one you
        recommended; never speculatively. Recommend first, let the user
        decide, then call. Use list_models for valid names."""
        return t.download_model(name=name)

    @agent.tool_plain
    def package_skill(name: str) -> dict:
        """Bundle a skill you built into a portable, shareable .zip with
        a generated manifest (name, version, deps, smoke-test status).
        Use this once a skill is proven and worth sharing. The bundle
        installs on any Jaeger-OS instance. Publishing it to the
        marketplace is a later step (the marketplace repo isn't live
        yet — see docs/marketplace_spec.md)."""
        return t.package_skill(name=name)

    @agent.tool_plain
    def benchmark_skill(name: str) -> dict:
        """Run a skill's scored benchmark (tests/benchmark.py) and track
        the delta vs. its last run. Use this when revising a skill:
        benchmark the old version, write the new one, benchmark again —
        `delta > 0` proves the revision helped. Same principle as the
        repo's level benchmarks, scoped to one skill."""
        return t.benchmark_skill(name=name)

    @agent.tool_plain
    def propose_deep_think_task(description: str) -> dict:
        """Queue a skill-development task for Deep Think to work later.
        Use when you notice something worth building/fixing that's too
        big for the current turn. The task is added UNAPPROVED — the
        user approves it before Deep Think runs it. You propose; the
        user decides."""
        return t.propose_deep_think_task(description=description)

    @agent.tool_plain
    def list_deep_think_queue() -> dict:
        """Read the Deep Think task queue with status counts. Read-only."""
        return t.list_deep_think_queue()

    @agent.tool_plain
    def board_view(column: str = "", tag: str = "") -> dict:
        """Read the kanban task board — what work is queued (ready),
        in_progress, blocked, or done. Optionally filter by `column` or
        `tag`. Deep Think jobs show here too (tag 'deepthink')."""
        return t.board_view(column=column, tag=tag)

    @agent.tool_plain
    def board_add(
        title: str, description: str = "",
        tags: list[str] | None = None, priority: str = "med",
    ) -> dict:
        """Add a card to the kanban board (lands in `ready`, set to
        work). Use this to lay out a multi-step task as cards so you and
        the user can track progress. `priority` is low/med/high."""
        return t.board_add(title=title, description=description,
                           tags=tags, priority=priority)

    @agent.tool_plain
    def board_move(card_id: str, column: str) -> dict:
        """Move a board card: `in_progress` when you start it, `done`
        when finished, `blocked` when it needs the user. You cannot move
        a card `backlog → ready` — that is the user's approval step."""
        return t.board_move(card_id=card_id, column=column)

    @agent.tool_plain
    def board_update(
        card_id: str, title: str = "", description: str = "",
        priority: str = "", add_tag: str = "", note: str = "",
        result: str = "",
    ) -> dict:
        """Edit a board card or log progress on it. `note` appends to
        the card's running log; `result` records the outcome. Empty
        arguments are left unchanged."""
        return t.board_update(card_id=card_id, title=title,
                              description=description, priority=priority,
                              add_tag=add_tag, note=note, result=result)

    @agent.tool_plain
    def start_background(code: str, name: str = "") -> dict:
        """Launch Python code as a background process that OUTLIVES this
        turn. Use this — not run_python / run_in_venv (which are capped
        and synchronous) — for work that takes minutes or longer: a long
        render, a bot that stays connected, a watcher. Runs against the
        instance venv. Returns a process_id; monitor with
        check_background, end with stop_background."""
        return t.start_background(code=code, name=name)

    @agent.tool_plain
    def list_background() -> dict:
        """List every background process with live status (running /
        exited / stopped, exit code, elapsed)."""
        return t.list_background()

    @agent.tool_plain
    def check_background(process_id: str, lines: int = 20) -> dict:
        """Status of one background process + the last `lines` lines of
        its output (default 20, max 2000 — raise it for fuller output).
        Use it to see whether a process you started is still running and
        what it produced."""
        return t.check_background(process_id=process_id, lines=lines)

    @agent.tool_plain
    def stop_background(process_id: str) -> dict:
        """Terminate a running background process by id."""
        return t.stop_background(process_id=process_id)

    @agent.tool_plain
    def clarify(question: str) -> dict:
        """Ask the user a clarifying question instead of guessing."""
        return t.ask_user(question=question)

    @agent.tool_plain
    def help_me() -> dict:
        """Capability overview — call when asked 'what can you do?'."""
        return t.help_me()

    @agent.tool_plain
    def get_credential(name: str) -> dict:
        """Look up a secret (API key, token) by name from the instance's
        credentials/ store. NEVER read credential files directly — this is
        the only sanctioned access path. The returned value is for tool
        use only; do NOT echo it back to the user in your reply.
        """
        return creds.get_credential_tool_result(_pipeline["layout"], name=name)

    @agent.tool_plain
    def list_credentials() -> dict:
        """List the names of every credential currently stored. Values
        are never returned by this tool — use get_credential(name) for
        the actual value, and never echo the value in your reply."""
        return {"credentials": creds.list_credentials(_pipeline["layout"])}

    # ------------------------------------------------------------------
    # Parity ports from python_pydantic_ai — TTS, vision, host, sub-agent,
    # semantic memory. Each tool's docstring is what the LLM sees.
    # ------------------------------------------------------------------
    @agent.tool_plain
    def text_to_speech(text: str = "", path: str = "") -> dict:
        """Speak text aloud through the default audio output via Kokoro
        TTS. Use ONLY when the user explicitly asks to HEAR something
        ("say…", "out loud", "narrate/read X aloud", "speak"). This is
        NOT your reply channel — ordinary questions ("tell me a joke",
        "what's the weather") are answered in text, not spoken.
        Pass `text` for literal text, or `path` to narrate a file from
        <instance>/skills/ ("read X out loud", "narrate X" with a named
        file). `path` is sandbox-resolved and wins over `text` when both
        are given. Supports minimal SSML: <break time="200ms"/>, <breath/>."""
        return t.speak(text=text, path=path)

    @agent.tool_plain
    def vision_analyze(image_path: str, question: str = "Describe this image in one short sentence.") -> dict:
        """Look at a workspace image and answer a question about it.
        Default backbone: Moondream2 (~1.9B VLM, Apache-2.0). image_path is
        sandbox-resolved under <instance>/skills/. First call lazy-loads
        the VLM on CPU."""
        return t.look_at(image_path=image_path, question=question)

    @agent.tool_plain
    def image_generate(
        prompt: str,
        out_path: str = "generated.png",
        num_inference_steps: int = 1,
        guidance_scale: float = 0.0,
        seed: int | None = None,
    ) -> dict:
        """Generate an image from a text prompt and save under skills/.
        Default backbone: SDXL-Turbo (1-step). First call downloads ~6 GB
        of weights; subsequent calls are 1-3s per image."""
        return t.generate_image(
            prompt=prompt, out_path=out_path,
            num_inference_steps=num_inference_steps,
            guidance_scale=guidance_scale, seed=seed,
        )

    @agent.tool_plain
    def open_on_host(target: str, kind: str = "auto") -> dict:
        """Open something on the host (macOS). One verb for three cases:
        a URL in the default browser, a workspace file in its default
        app, or a macOS application by name. `kind` is "auto" (default),
        "url", "file", or "app" — "auto" classifies the target (http →
        URL, an existing skills/ file → file, else → app name). File
        targets are sandbox-resolved under <instance>/skills/."""
        return t.open_on_host(target=target, kind=kind)

    @agent.tool_plain
    def search_memory(query: str, k: int = 5) -> dict:
        """Semantic search over this instance's episodic conversation log.
        Use when `recall` (exact key) misses — e.g. "what did we talk
        about yesterday?", "did I tell you about my dog?". Returns top-k
        past turns with cosine-similarity scores."""
        return t.search_memory(query=query, k=k)

    @agent.tool_plain
    def delegate_task(subtasks: list[str]) -> dict:
        """Hand focused subtasks to fresh sub-agents. Pass a list: one
        item runs a single sub-agent; 2+ items fan out across up to 2
        concurrent sub-agents. Each sub-agent runs in its own context
        (no parent history) but shares the instance's memory and tools.
        Sub-agents share the one loaded model, so their LLM turns
        serialize — the benefit is clean fan-out/collect, not raw speed.
        Depth-limited. For sustained background work, prefer Deep Think
        (/deepthink) over delegation."""
        clean = [s for s in (subtasks or []) if s and s.strip()]
        if not clean:
            return {"delegated": False, "error": "no subtasks given"}
        if len(clean) == 1:
            return _delegate_internal(client, clean[0])
        return _delegate_parallel(client, clean)

    @agent.tool_plain
    def send_message(channel: str, recipient: str, text: str) -> dict:
        """Send a proactive message to a user on a messaging channel.

        Available `channel` values depend on which bridges are live in
        this process — typically "discord", "telegram", "imessage".
        `recipient` is the channel-specific ID (numeric Discord user ID,
        Telegram chat ID, or iMessage phone/Apple-ID handle).

        Use this together with `schedule_prompt` to send unattended
        notifications: schedule a prompt that says "send the weather to
        Discord user 12345" and the cron runner will fire it on time.
        """
        text_clean = (text or "").strip()
        channel_clean = (channel or "").strip().lower()
        recipient_clean = (recipient or "").strip()
        if not channel_clean or not recipient_clean or not text_clean:
            return {"sent": False, "error": "channel, recipient, and text are all required"}
        try:
            from .plugins import get_bridge, list_bridges
        except Exception as exc:
            return {"sent": False, "error": f"messaging plugin not importable: {exc}"}
        bridge = get_bridge(channel_clean)
        if bridge is None:
            return {
                "sent": False,
                "error": f"no bridge registered for {channel_clean!r}; live bridges: {list_bridges()}",
            }
        try:
            return bridge.send(recipient_clean, text_clean)
        except Exception as exc:
            return {"sent": False, "error": f"bridge.send failed: {type(exc).__name__}: {exc}"}

    @agent.tool_plain
    def reload_skills() -> dict:
        """Re-scan core skills/ + instance skills/ and register any
        newly-authored or newly-versioned skills onto this agent.

        Call this after you've finished writing all the files for a new
        skill (SKILL.md + module + tests/smoke_test.py). The loader runs
        each skill's smoke test before activation; a failing test means
        the skill is NOT registered and you must fix the skill (not the
        test) before retrying. Returns the names of skills newly
        registered this call."""
        from .core.skill_loader import load_and_register, _REGISTERED_KEYS
        cfg = _pipeline["config"]
        before = {(n, v, z) for (n, v, z) in _REGISTERED_KEYS}
        report = load_and_register(
            agent,
            _pipeline["layout"],
            run_smoke_tests=cfg.skills.run_smoke_tests,
            enabled_allowlist=list(cfg.skills.enabled_base_skills) or None,
            audit=lambda ev, payload: jaeger_tools._audit(ev, payload),
        )
        after = set(_REGISTERED_KEYS)
        newly = sorted(after - before)
        return {
            "newly_registered": [
                {"name": n, "version": v, "zone": z} for (n, v, z) in newly
            ],
            "skipped": [
                {"name": s.name, "version": s.version, "zone": s.zone, "reason": reason[:200]}
                for (s, reason) in report.skipped
            ],
            "total_registered": len(after),
        }

    @agent.tool_plain
    def list_plugins() -> dict:
        """Enumerate the bundled jaeger_os plugins (discord, telegram,
        imessage, whisper_stt, kokoro_tts, mcp) with install + credential
        status for each. Use this when the user asks what integrations
        are available, or before suggesting a feature you'd need a
        plugin for."""
        return t.list_plugins()

    @agent.tool_plain
    def setup_plugin(name: str) -> dict:
        """Return step-by-step setup instructions for the named plugin
        (e.g. ``discord``, ``telegram``, ``whisper_stt``). Surfaces
        missing libraries to ``pip install`` and required env vars or
        credentials that need values. Does NOT modify the user's
        environment — the user runs the install commands and stores
        credentials themselves."""
        return t.setup_plugin(name=name)

    @agent.tool_plain
    def listen(seconds: int = 5) -> dict:
        """Record N seconds of microphone audio and return the transcript.

        Use when the user asks you to listen, or when you need to capture
        spoken input mid-chat. Atomic: mic opens, records, closes — no
        always-on listening. Cap is 60s; for hands-free conversation, tell
        the user to launch ``python -m jaeger_os --voice`` instead.

        Returns ``{ok, transcript, seconds, model, elapsed_s}`` on success."""
        return t.listen(seconds=seconds)


# ---------------------------------------------------------------------------
# Sub-agent delegate — recursive invocation with depth guard
# ---------------------------------------------------------------------------
_DELEGATE_MAX_DEPTH = int(os.environ.get("DELEGATE_MAX_DEPTH", "2"))
_delegate_depth = threading.local()


def _delegate_internal(client: Any, subtask: str) -> dict[str, Any]:
    """Run a subtask through the same agent loop with a fresh history.

    Same pattern python_pydantic_ai uses: bumps a thread-local depth
    counter, runs the subtask, returns the answer + elapsed time.
    Depth-limited to prevent runaway recursion if a sub-agent decides
    to delegate again.
    """
    depth = getattr(_delegate_depth, "value", 0)
    if depth >= _DELEGATE_MAX_DEPTH:
        return {
            "delegated": False,
            "error": f"delegate recursion limit hit ({_DELEGATE_MAX_DEPTH}); "
                     "the sub-agent tried to delegate again — refusing.",
        }
    clean = (subtask or "").strip()
    if not clean:
        return {"delegated": False, "error": "empty subtask"}

    _delegate_depth.value = depth + 1
    started = time.perf_counter()
    try:
        agent = _get_agent(client)
        # Serialize model access through the shared llm_lock. Sequential
        # delegate was already one-at-a-time, but delegate_parallel runs
        # _delegate_internal from worker threads — llama-cpp can't decode
        # two prompts at once, so the lock is mandatory there.
        lock = _pipeline.get("llm_lock")
        if lock is not None:
            with lock:
                iter_out = asyncio.run(_run_via_iter(agent, clean, None, client=client))
        else:
            iter_out = asyncio.run(_run_via_iter(agent, clean, None, client=client))
    except Exception as exc:
        _delegate_depth.value = depth
        return {"delegated": False, "error": f"{type(exc).__name__}: {exc}"}
    finally:
        _delegate_depth.value = depth

    elapsed = time.perf_counter() - started
    if iter_out.get("skipped"):
        answer = iter_out.get("skipped_text") or ""
    else:
        result = iter_out.get("result")
        answer = (getattr(result, "output", None) if result else "") or ""
    return {
        "delegated": True,
        "subtask": clean,
        "answer": str(answer).strip(),
        "depth": depth + 1,
        "elapsed_s": round(elapsed, 3),
    }


# Hard cap on concurrent subagents. The robot is memory-bound — all
# subagents share the ONE loaded Gemma model (no second model load),
# and llama-cpp serializes decode, so 2 is the practical ceiling.
# For sustained background work prefer Deep Think (sequential queue +
# model swap) over fanning out parallel subagents.
_MAX_PARALLEL_SUBAGENTS = 2


def _delegate_parallel(client: Any, subtasks: list[str]) -> dict[str, Any]:
    """Fan a small set of subtasks out across up to
    :data:`_MAX_PARALLEL_SUBAGENTS` worker threads.

    All subagents share the one loaded Gemma model. llama-cpp can't
    decode two prompts at once, so each subagent's model access
    serializes through ``_pipeline['llm_lock']`` — the win here is
    orchestration (queue N, collect all answers) plus overlap on
    non-LLM tool work, NOT raw decode speedup. For sustained
    background work, Deep Think is the better mechanism.

    More than the cap of subtasks is allowed — the thread pool runs
    the cap at a time and queues the rest. Returns one result entry
    per subtask, in input order."""
    from concurrent.futures import ThreadPoolExecutor

    clean = [s.strip() for s in (subtasks or []) if s and s.strip()]
    if not clean:
        return {"ok": False, "error": "no subtasks given"}

    parent_depth = getattr(_delegate_depth, "value", 0)
    if parent_depth >= _DELEGATE_MAX_DEPTH:
        return {
            "ok": False,
            "error": f"delegate recursion limit hit ({_DELEGATE_MAX_DEPTH})",
        }

    def _worker(task: str) -> dict[str, Any]:
        # Worker runs on a fresh thread — _delegate_depth is
        # thread-local, so seed it here to keep nested delegation
        # bounded.
        _delegate_depth.value = parent_depth + 1
        try:
            return _delegate_internal(client, task)
        finally:
            _delegate_depth.value = parent_depth

    started = time.perf_counter()
    with ThreadPoolExecutor(
        max_workers=_MAX_PARALLEL_SUBAGENTS,
        thread_name_prefix="subagent",
    ) as pool:
        results = list(pool.map(_worker, clean))
    elapsed = time.perf_counter() - started

    succeeded = sum(1 for r in results if r.get("delegated"))
    return {
        "ok": True,
        "subtask_count": len(clean),
        "max_concurrent": _MAX_PARALLEL_SUBAGENTS,
        "succeeded": succeeded,
        "failed": len(clean) - succeeded,
        "results": results,
        "elapsed_s": round(elapsed, 3),
    }


def _build_mcp_tools(specs: list[Any]) -> list[Any]:
    """Build Pydantic AI Tool objects for every MCP tool the bridge exposes.

    Each MCP tool's advertised JSON Schema becomes the pydantic-ai tool
    schema directly via Tool.from_schema, so adding a new MCP server in
    plugins/mcp_config.json automatically surfaces its tools — no code
    change required.
    """
    if not specs:
        return []
    from pydantic_ai import Tool

    tools_list: list[Any] = []
    for spec in specs:
        schema = spec.input_schema if isinstance(spec.input_schema, dict) else {}
        if not schema or "type" not in schema:
            schema = {"type": "object", "properties": {}, **schema}

        def _make_caller(qualified_name: str):
            def _call(**kwargs: Any) -> dict[str, Any]:
                from .plugins.mcp import client as mcp_client
                return mcp_client.call_mcp_tool(qualified_name, kwargs)
            _call.__name__ = qualified_name.replace(":", "_").replace("/", "_")
            return _call

        tools_list.append(
            Tool.from_schema(
                function=_make_caller(spec.qualified_name),
                name=spec.qualified_name,
                description=spec.description or f"MCP tool {spec.qualified_name}",
                json_schema=schema,
            )
        )
    return tools_list


def build_agent(client: Any, system_prompt: str, mcp_specs: list[Any] | None = None) -> Agent[None, str]:
    # ``client.model`` is the pydantic-ai Model: a LlamaCppModel for the
    # local llama-cpp client, or a native OpenAIChatModel / AnthropicModel
    # for the external-model client. The agent loop is the same either way.
    model = client.model
    # ``tool_retries=`` was renamed to ``retries=`` in pydantic-ai 1.x;
    # the kwarg controls how many times the agent re-prompts the model
    # when a tool's typed args fail validation.
    agent: Agent[None, str] = Agent(
        model=model,
        system_prompt=system_prompt,
        retries=2,
        tools=_build_mcp_tools(mcp_specs or []),
    )
    _register_builtins(agent, client)
    return agent


# ---------------------------------------------------------------------------
# agent.iter() drive loop with skip-final intercept
# ---------------------------------------------------------------------------
_FAST_FINALIZE_DIRECTIVE = (
    "You just called the `{tool}` tool. The tool returned:\n"
    "{result}\n\n"
    "Reply to the user's original question in ONE short, natural sentence "
    "using that result. Do NOT call any more tools. Plain text only."
)


def _fast_finalize_sync(
    client: Any,
    user_text: str,
    tool_name: str,
    tool_result: Any,
    *,
    max_tokens: int = 120,
) -> str:
    """Bounded single-shot LLM call that turns a tool result into a
    one-sentence user-facing answer.

    The "skip-final" tools used to bypass the LLM entirely — fast, but
    the user saw raw dicts ("2026-05-19 04:50:09 PM PDT") instead of
    conversational answers ("It's 4:50 PM"). This helper keeps the LLM
    IN the loop on those turns while capping token count + temperature
    so the cost stays close to the original bypass (~0.3-0.7s vs
    ~1.5-2s for an unconstrained finalize). Falls back to the raw
    formatter on any client/model failure."""
    formatted = _format_tool_result_as_answer(tool_name, tool_result)
    # Nothing to finalize — e.g. text_to_speech: the audio IS the output,
    # so the formatted answer is empty. Running the LLM on an empty
    # result makes it HALLUCINATE a fresh answer (a different joke than
    # the one just spoken). Return the empty/short answer directly.
    if not formatted.strip():
        return formatted
    # text_to_speech: the spoken line IS the answer, verbatim — a
    # finalize pass would paraphrase the line the user just heard.
    if tool_name == "text_to_speech":
        return formatted
    if client is None:
        return formatted
    system = _pipeline.get("system_prompt") or ""
    directive = _FAST_FINALIZE_DIRECTIVE.format(tool=tool_name, result=formatted)
    try:
        result = client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
                {"role": "user", "content": directive},
            ],
            max_tokens=max_tokens,
            temperature=0.2,
            top_p=0.9,
            stream=False,
            # Carry the decide call's tool schemas so this finalize
            # renders the identical <system + tools> prefix and reuses
            # the warm KV instead of evicting it.
            tools=_pipeline.get("openai_tools"),
        )
        text = (getattr(result, "text", None) or "").strip()
        # Strip any drift tool-call markup the model leaked into the
        # final-text response (e.g. Gemma emitting
        # ``<|tool_call>call:recall(key='x')<tool_call|>`` mid-text).
        # Without this, the user sees raw markup; with it, we surface
        # just the prose. NB: we don't try to EXECUTE the leaked tool
        # call here — that'd require another agent.iter pass and we're
        # already in the fast-finalize fast path. The multi-step
        # detector upstream is what gives the model a chance to chain.
        text = _strip_drift_markup(text)
        return text or formatted
    except Exception:
        return formatted


def _strip_drift_markup(text: str) -> str:
    """Remove any of the four drift tool-call markup patterns from
    ``text`` and return what's left. Lazy import of the patterns so the
    bench / non-LLM call paths don't pay the cost."""
    if not text or "<" not in text:
        return text
    from .core.llm_model import _DRIFT_PATTERNS
    cleaned = text
    for pattern in _DRIFT_PATTERNS:
        cleaned = pattern.sub("", cleaned)
    return cleaned.strip()


# Imperative verbs that strongly imply a tool call. Used in two-pass
# detection: count how many distinct imperatives appear in the prompt.
_IMPERATIVE_VERBS = (
    r"run|read|write|save|delete|append|cancel|list|tell|recall|"
    r"remember|forget|fetch|search|speak|narrate|create|make|open|"
    r"launch|use|call|verify|confirm|reload|schedule|calculate|"
    r"compute|count|show|find|look\s*up|check|store|set|build|"
    # Edit-intent verbs — "finish the code", "fix the file" are
    # implicitly read-then-write tasks. Including them here lets the
    # two-verb counter trip multi-step for prompts like "fix and run".
    r"finish|complete|fix|implement|edit|update|modify|improve|"
    r"rewrite|refactor|debug|correct"
)
# Sequential connectors that explicitly indicate "this is the next step".
# Allows optional adverbs between the connector and the verb, e.g.
# "then immediately recall" or "and then quickly run".
_CONNECTOR_THEN_VERB = re.compile(
    rf"\b(?:then|and(?:\s+then)?|after\s+(?:that|writing|creating|saving|"
    rf"running|reading|fetching)|next,?|finally,?)\s+(?:\w+\s+){{0,2}}"
    rf"(?:{_IMPERATIVE_VERBS})\b",
    re.IGNORECASE,
)
# Direct imperative-verb count — three or more in one prompt is also
# a strong "multi-step" signal even without explicit connectors
# ("write fib.py and run it" has both "write" and "run").
_VERB_COUNTER = re.compile(rf"\b({_IMPERATIVE_VERBS})\b", re.IGNORECASE)


def _looks_multistep(user_text: str) -> bool:
    """Return True when the user's prompt looks like it needs more than
    one tool call. Two checks:
      1. Explicit sequential connectors ("then run", "after writing")
      2. Two or more distinct imperative verbs ("write fib.py and run it")

    When this fires, ``_run_via_iter`` suppresses the skip-final
    shortcut so agent.iter runs the full loop and the model can chain
    into the next tool naturally. Skip-final is great for single-shot
    questions but actively breaks multi-step requests."""
    if not user_text:
        return False
    if _CONNECTOR_THEN_VERB.search(user_text):
        return True
    verbs = {m.group(1).lower() for m in _VERB_COUNTER.finditer(user_text)}
    return len(verbs) >= 2


async def _run_via_iter(
    agent: Agent,
    user_text: str,
    message_history: list[Any] | None,
    *,
    client: Any = None,
) -> dict[str, Any]:
    first_decision: dict[str, Any] | None = None
    skip_final = False
    skip_tool_name: str | None = None
    skip_result: Any = None
    # Multi-step prompts: don't short-circuit on the first tool call,
    # let the full agent.iter loop run so the model can chain naturally.
    suppress_skip_final = _looks_multistep(user_text)

    async with agent.iter(user_text, message_history=message_history or None) as run:
        async for node in run:
            if isinstance(node, CallToolsNode):
                tool_parts = [p for p in node.model_response.parts if hasattr(p, "tool_call_id")]
                if first_decision is None and tool_parts:
                    tc = tool_parts[0]
                    first_decision = {"tool": tc.tool_name, "args": tc.args}
                    if (
                        not suppress_skip_final
                        and len(tool_parts) == 1
                        and tc.tool_name in SKIP_FINAL_TOOLS
                    ):
                        skip_final = True
                        skip_tool_name = tc.tool_name
            if skip_final and isinstance(node, ModelRequestNode):
                for p in node.request.parts:
                    if isinstance(p, ToolReturnPart):
                        skip_result = p.content
                        break
                if skip_result is not None:
                    break
        else:
            return {"result": run.result, "skipped": False, "first_decision": first_decision}

    # Fast-finalize: bounded LLM call that paraphrases the tool result
    # into a natural sentence. Falls back to the raw formatter when
    # ``client`` isn't threaded through (legacy callers, tests).
    text = _fast_finalize_sync(client, user_text, skip_tool_name or "", skip_result)
    skipped_msgs = [
        ModelRequest(parts=[UserPromptPart(content=user_text)]),
        ModelResponse(
            parts=[TextPart(content=text)],
            usage=RequestUsage(input_tokens=0, output_tokens=0),
            model_name="local-gemma-4-26b-a4b",
            timestamp=datetime.now(timezone.utc),
        ),
    ]
    return {
        "result": None, "skipped": True, "skipped_text": text,
        "skipped_msgs": skipped_msgs, "skipped_result": skip_result,
        "first_decision": first_decision,
    }


def _walk_new_messages(result: Any) -> tuple[list[str], dict[str, Any] | None]:
    out: list[str] = []
    first_decision: dict[str, Any] | None = None
    pending_calls: dict[str, dict[str, Any]] = {}
    try:
        msgs = list(result.new_messages()) if hasattr(result, "new_messages") else list(result.all_messages())
    except Exception:
        return out, None
    for msg in msgs:
        kind = getattr(msg, "kind", None)
        if kind == "response":
            for part in msg.parts:
                if getattr(part, "part_kind", None) == "tool-call":
                    pending_calls[part.tool_call_id] = {"name": part.tool_name, "args": part.args}
                    if first_decision is None:
                        first_decision = {"tool": part.tool_name, "args": part.args}
        elif kind == "request":
            for part in msg.parts:
                if getattr(part, "part_kind", None) != "tool-return":
                    continue
                call = pending_calls.pop(getattr(part, "tool_call_id", None), None)
                name = (call or {}).get("name") or part.tool_name
                args = (call or {}).get("args") or {}
                args_repr = ""
                if isinstance(args, dict) and args:
                    args_repr = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2])
                    if len(args_repr) > 60:
                        args_repr = args_repr[:57] + "..."
                out.append(f"  ▸ {name}({args_repr})")
    return out, first_decision


# ---------------------------------------------------------------------------
# Phase-4 inline thinking. Opt-in (env: JAEGER_INLINE_THINK=1) brief
# chain-of-thought call BEFORE the main agent turn, on prompts the
# heuristic flags as complex (long, or contains code keywords). The
# thought is prepended to the user turn so the model sees its own
# plan before deciding what tool to call. Default: OFF — adds 1-3s
# of latency per qualifying turn, which the bench shouldn't pay
# unless explicitly opted in.
# ---------------------------------------------------------------------------
_INLINE_THINK_DIRECTIVE = (
    "Before answering the user's request, think briefly about it in 3-5 "
    "short bullets:\n"
    "  1. What does the user actually want?\n"
    "  2. What tools or steps would solve it?\n"
    "  3. Likely failure modes (truncated code, ambiguous wording, "
    "missing context)?\n"
    "Plain text only. Do NOT call any tools in this response — analysis "
    "only. Keep under 150 words."
)

_INLINE_THINK_KEYWORDS = frozenset({
    "code", "script", "python", "function", "class ",
    "implement", "build", "create a", "write a",
    "fix the", "debug", "refactor", "rewrite",
    "test the", "test it", "run_python",
})


def _should_inline_think(user_text: str) -> bool:
    """Heuristic gate for the Phase-4 inline-thinking pre-pass.

    Fires when the env var JAEGER_INLINE_THINK is set AND the user
    prompt looks non-trivial (long, or contains code-task keywords).
    Keep the trigger conservative — the latency cost compounds across
    a long bench, and most simple prompts don't need a plan."""
    if os.environ.get("JAEGER_INLINE_THINK") != "1":
        return False
    if not user_text:
        return False
    if len(user_text) > 120:
        return True
    lower = user_text.lower()
    return any(kw in lower for kw in _INLINE_THINK_KEYWORDS)


def _inline_think_sync(client: Any, user_text: str) -> str | None:
    """Synchronous one-shot chain-of-thought call. Returns the thought
    text (stripped) or None on any failure. Uses the same client and
    system prompt as the agent so the KV-cache prefix is shared.

    The lock is held in the caller (``_run_with_fix_loop``); we do not
    re-acquire it here to avoid a deadlock against a re-entrant caller."""
    try:
        system = _pipeline.get("system_prompt") or ""
        result = client.chat(
            [
                {"role": "system", "content": system},
                {"role": "user", "content": user_text},
                {"role": "user", "content": _INLINE_THINK_DIRECTIVE},
            ],
            max_tokens=300,
            temperature=0.6,
            top_p=0.95,
            stream=False,
        )
        return (getattr(result, "text", None) or "").strip() or None
    except Exception:
        return None


def _augment_with_thought(user_text: str, thought: str) -> str:
    """Prepend the inline thought to user_text as a marked block so
    the model can read its own plan before deciding what to do."""
    return (
        "[my plan for this turn — internal, do not echo back]\n"
        f"{thought}\n"
        "[end plan]\n\n"
        f"{user_text}"
    )


# ---------------------------------------------------------------------------
# Phase-3 run-and-fix loop. Detects a failed ``run_python`` in the
# completed iter_out, builds a follow-up "fix this and retry" user
# turn, and re-runs the agent with the prior messages as history so
# it knows what code it wrote. Capped at 1 extra pass — the system
# prompt promises the model ONE retry, not infinite.
# ---------------------------------------------------------------------------
_RETRY_PROMPT_TEMPLATE = (
    "The previous `run_python` call failed. Stderr:\n```\n{stderr}\n```\n"
    "Read the file with `read_file`, fix the bug, write it back with "
    "`write_file`, and re-run with `run_python`. Do not give up."
)


def _find_failed_run_python(iter_out: dict[str, Any]) -> dict[str, Any] | None:
    """Return the ``run_python`` tool's result dict if it ran and failed
    (``ok=False`` AND not ``timed_out``), else None. Walks both the
    skip-final and full-iter shapes so it works regardless of which path
    the turn took."""
    # Skip-final: first_decision points at the tool, skipped_result holds
    # the dict (added by the iter when present).
    fd = iter_out.get("first_decision") or {}
    if fd.get("tool") == "run_python":
        skip_result = iter_out.get("skipped_result")
        if isinstance(skip_result, dict):
            return _run_python_failure_if_any(skip_result)
    # Full-iter: walk the agent result's messages for run_python returns.
    result = iter_out.get("result")
    if result is None:
        return None
    try:
        msgs = list(result.all_messages()) if hasattr(result, "all_messages") else []
    except Exception:
        return None
    pending: dict[str, str] = {}
    for msg in msgs:
        kind = getattr(msg, "kind", None)
        if kind == "response":
            for part in msg.parts:
                if getattr(part, "part_kind", None) == "tool-call":
                    pending[part.tool_call_id] = part.tool_name
        elif kind == "request":
            for part in msg.parts:
                if getattr(part, "part_kind", None) != "tool-return":
                    continue
                name = pending.pop(getattr(part, "tool_call_id", None), None) \
                    or getattr(part, "tool_name", None)
                if name != "run_python":
                    continue
                content = getattr(part, "content", None)
                if isinstance(content, dict):
                    failure = _run_python_failure_if_any(content)
                    if failure is not None:
                        return failure
    return None


def _run_python_failure_if_any(result: dict[str, Any]) -> dict[str, Any] | None:
    """Return ``result`` if it represents a fixable failure, else None.
    Timeouts are NOT retried — an infinite loop won't get smarter on
    a second try, and the wall-clock cost would compound."""
    if result.get("ok"):
        return None
    if result.get("timed_out"):
        return None
    if not (result.get("stderr") or result.get("error")):
        return None
    return result


async def _run_with_fix_loop(
    agent: Agent,
    user_text: str,
    message_history: list[Any] | None,
    *,
    max_retries: int = 1,
    client: Any = None,
) -> dict[str, Any]:
    """Wrapper around :func:`_run_via_iter` that:
      1. Optionally pre-pends an inline chain-of-thought (Phase 4) when
         ``JAEGER_INLINE_THINK=1`` and the prompt looks complex.
      2. Injects ONE retry pass (Phase 3) if a ``run_python`` call fails.

    Disabled (max_retries=0) for any caller that doesn't want the retry
    cost / non-determinism. ``client`` is needed for the inline-think
    call; when None, the think pass is silently skipped."""
    history = message_history
    effective_text = user_text
    if client is not None and _should_inline_think(user_text):
        thought = _inline_think_sync(client, user_text)
        if thought:
            effective_text = _augment_with_thought(user_text, thought)
    iter_out = await _run_via_iter(agent, effective_text, history, client=client)
    for _ in range(max_retries):
        failure = _find_failed_run_python(iter_out)
        if failure is None:
            return iter_out
        # Build the retry history from the just-finished run so the
        # model sees its own prior tool calls. Falls back to whatever
        # we had if the result object doesn't expose all_messages().
        result = iter_out.get("result")
        if result is not None and hasattr(result, "all_messages"):
            try:
                history = list(result.all_messages())
            except Exception:
                pass
        elif iter_out.get("skipped_msgs"):
            history = (history or []) + list(iter_out["skipped_msgs"])
        stderr = (failure.get("stderr") or failure.get("error") or "")[:1500]
        retry_text = _RETRY_PROMPT_TEMPLATE.format(stderr=stderr.strip())
        iter_out = await _run_via_iter(agent, retry_text, history, client=client)
        # Mark so callers / logs can see this was a retry-loop turn.
        iter_out["retried_after_run_python_failure"] = True
    return iter_out


# ---------------------------------------------------------------------------
# run_command — the chat-loop entry point
# ---------------------------------------------------------------------------
_agent_cache: dict[tuple, Agent[None, str]] = {}


def _agent_key(client: Any) -> tuple:
    mcp_fingerprint = tuple(sorted(
        getattr(s, "qualified_name", "") for s in _pipeline.get("mcp_specs") or []
    ))
    return (id(client), hash(_pipeline["system_prompt"]), mcp_fingerprint)


def _get_agent(client: Any) -> Agent[None, str]:
    key = _agent_key(client)
    if key not in _agent_cache:
        _agent_cache.clear()
        agent = build_agent(client, _pipeline["system_prompt"], _pipeline.get("mcp_specs"))
        # Skill loader registers base + instance skills AFTER built-ins,
        # so an instance skill named `get_time_v2` would override the
        # built-in (intentional; honors the v2 override-via-versioning rule).
        load_and_register(
            agent,
            _pipeline["layout"],
            run_smoke_tests=_pipeline["config"].skills.run_smoke_tests,
            enabled_allowlist=list(_pipeline["config"].skills.enabled_base_skills) or None,
            audit=lambda ev, payload: jaeger_tools._audit(ev, payload),
        )
        _agent_cache[key] = agent
    return _agent_cache[key]


def prewarm(client: Any) -> None:
    """Prime the KV cache so the first user-facing turn isn't cold.

    The first agent call against a freshly-loaded model pays a ~1 s
    prefill cost to tokenize the (long) v2 system prompt + the tool
    schema. By running a single trivial turn at startup, we shift that
    cost from "what time is it" to the load phase — where the user
    already accepts a wait. Idempotent. Mirrors python_pydantic_ai.prewarm.
    """
    if _pipeline.get("prewarmed"):
        return
    # External models have no local KV cache to prime — and make_client
    # already ran a live connectivity check. Skip the extra API round.
    if getattr(client, "kind", "local") == "external":
        _pipeline["prewarmed"] = True
        return
    started = time.perf_counter()
    try:
        agent = _get_agent(client)
        # A trivial free-text prompt: pays decode for system prompt +
        # tool schema prefill + a handful of generation tokens. Result
        # discarded — no history, no log.
        agent.run_sync("Respond with just the word ready.")
    except Exception as exc:
        print(f"[jaeger] prewarm skipped: {exc}", flush=True)
        return
    _pipeline["prewarmed"] = True
    print(f"[jaeger] agent prewarmed in {time.perf_counter() - started:.1f}s", flush=True)


def warm_plugins(config: Any) -> None:
    """Boot-time plugin warmup — per ``config.warmup``, pre-load TTS /
    STT / vision so the Jaeger is fully operational the instant boot
    finishes, not on first use. Each warm is timed and best-effort: a
    failure prints a warning and never blocks boot. Robots run TTS/STT
    constantly, so those default on (see :class:`WarmupConfig`)."""
    w = getattr(config, "warmup", None)
    if w is None:
        return
    jobs: list[tuple[str, Any]] = []
    if getattr(w, "tts", False):
        from .core.tools.speak import warm_kokoro
        jobs.append(("TTS (Kokoro)", warm_kokoro))
    if getattr(w, "stt", False):
        from .core.tools.listen import warm_listen
        jobs.append(("STT (Whisper)", warm_listen))
    if getattr(w, "vision", False):
        from .core.tools.vision import warm_vision
        jobs.append(("vision (Moondream2)", warm_vision))
    for name, fn in jobs:
        started = time.perf_counter()
        try:
            fn()
            print(f"[jaeger] warmed {name} in "
                  f"{time.perf_counter() - started:.1f}s", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[jaeger] warm {name} skipped: "
                  f"{type(exc).__name__}: {exc}", flush=True)


def _confirmation_provider(config: Any, layout: Any = None) -> Any:
    """Pick the permission confirmation provider for ``config``.

    'confirm' mode → the interactive console prompt. 'allow' mode →
    auto-approve (a trusted, unattended robot). The mode is chosen at
    first-boot setup and persisted in config.yaml, so the posture
    survives every restart. The TUI swaps in its own spinner-aware
    prompt for 'confirm' mode (see ``_install_confirmations``).

    ``layout`` supplies the instance dir so the console provider can
    load + persist per-skill grants (``<instance>/permissions.json``)."""
    mode = getattr(getattr(config, "permissions", None), "mode", "confirm")
    if mode == "allow":
        from .core.permissions import AllowAllProvider
        return AllowAllProvider()
    return ConsoleConfirmationProvider(instance_dir=getattr(layout, "root", None))


def _preflight_log() -> None:
    """Run the environment preflight and print a concise warning block
    if an optional dependency or system library is missing. Silent when
    everything is ready. Best-effort — preflight never blocks boot."""
    try:
        from .core.preflight import boot_warning, check_environment
        warning = boot_warning(check_environment())
        if warning:
            print(warning, flush=True)
    except Exception:  # noqa: BLE001
        pass


def run_command(client: Any, user_text: str, session_key: str | None = None) -> None:
    key = session_key or _DEFAULT_SESSION_KEY
    history = _get_session_history(key) if _pipeline["with_memory"] else None
    agent = _get_agent(client)
    # LlamaCppModel carries per-call timing instrumentation; external
    # models (OpenAIChatModel / AnthropicModel) don't — guard the calls.
    model: Any = agent.model
    if hasattr(model, "reset_timings"):
        model.reset_timings()
    lock = _pipeline["llm_lock"]
    started = time.perf_counter()
    try:
        if lock is not None:
            with lock:
                iter_out = asyncio.run(
                    _run_with_fix_loop(agent, user_text, history, client=client)
                )
        else:
            iter_out = asyncio.run(
                _run_with_fix_loop(agent, user_text, history, client=client)
            )
    except Exception as exc:
        elapsed = time.perf_counter() - started
        print(f"Jaeger agent failed: {exc}")
        report = LatencyReport(elapsed, 0, 0.0, 0.0, 0.0, 0.0, 0.0)
        if _pipeline.get("show_latency"):
            print_latency(report)
        write_log({"user": user_text, "session_key": key, "error": str(exc),
                   "latency": asdict(report)})
        return

    elapsed = time.perf_counter() - started
    skipped = iter_out["skipped"]
    first_decision = iter_out["first_decision"]
    result = iter_out.get("result")

    if skipped:
        answer = iter_out["skipped_text"]
        if first_decision is not None:
            args = first_decision.get("args") or {}
            args_repr = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2]) if isinstance(args, dict) else ""
            tool_activity = [f"  ▸ {first_decision['tool']}({args_repr})"]
        else:
            tool_activity = []
    else:
        answer = result.output if hasattr(result, "output") else str(result)
        tool_activity, walked = _walk_new_messages(result)
        first_decision = first_decision or walked

    llm_times = list(getattr(model, "last_call_times", []))
    decision_total = sum(llm_times)
    decision_first = llm_times[0] if llm_times else 0.0
    final_last = llm_times[-1] if len(llm_times) >= 1 else 0.0
    report = LatencyReport(
        total=elapsed,
        tool_calls=len(tool_activity),
        decision=decision_total,
        decision_ttft=decision_first,
        tool=max(0.0, elapsed - decision_total),
        final=final_last if len(llm_times) > 1 else 0.0,
        final_ttft=final_last if len(llm_times) > 1 else 0.0,
    )

    if _pipeline.get("show_tool_activity", True):
        for line in tool_activity:
            print(line)
    if answer:
        print(answer)
    if _pipeline.get("show_latency"):
        print_latency(report)
        if skipped:
            print("  (final-LLM skipped — tool result returned directly)")

    write_log({
        "user": user_text,
        "session_key": key,
        "answer": answer,
        "tool_calls": len(tool_activity),
        "tool_activity": tool_activity,
        "decision": first_decision,
        "skipped_final": skipped,
        "latency": asdict(report),
    })

    if _pipeline["with_memory"] and history is not None:
        if skipped:
            history.extend(iter_out["skipped_msgs"])
        else:
            try:
                new_msgs = result.new_messages() if hasattr(result, "new_messages") else result.all_messages()
            except Exception:
                new_msgs = []
            history.extend(new_msgs)
        overflow = len(history) - _MAX_HISTORY_MESSAGES
        if overflow > 0:
            del history[:overflow]

    runner = _pipeline["thinking_runner"]
    if runner is not None:
        runner.queue(user_text, run_id=os.environ.get("BENCH_RUN_ID"))


# ---------------------------------------------------------------------------
# Bridging API — for plugins/messaging_gateway.py and other entry points
# that need a structured-dict return rather than print-to-stdout.
# ---------------------------------------------------------------------------
def run_for_voice(client: Any, user_text: str, session_key: str | None = None) -> dict[str, Any]:
    """Same agent loop as `run_command`, but returns a dict instead of
    printing. Mirrors python_pydantic_ai.run_for_voice. Messaging bridges
    pass channel-specific session_keys ("telegram:12345", "discord:67890")
    so each chat keeps its own context."""
    key = session_key or "voice"
    history = _get_session_history(key) if _pipeline["with_memory"] else None
    agent = _get_agent(client)
    model: Any = agent.model
    if hasattr(model, "reset_timings"):
        model.reset_timings()
    lock = _pipeline["llm_lock"]
    started = time.perf_counter()
    try:
        if lock is not None:
            with lock:
                iter_out = asyncio.run(_run_via_iter(agent, user_text, history))
        else:
            iter_out = asyncio.run(_run_via_iter(agent, user_text, history))
    except Exception as exc:
        return {
            "text": "", "error": str(exc), "tool_activity": [],
            "spoke_via_tool": False,
            "elapsed_s": time.perf_counter() - started,
        }

    elapsed = time.perf_counter() - started
    skipped = iter_out["skipped"]
    first_decision = iter_out["first_decision"]
    result = iter_out.get("result")

    if skipped:
        text = iter_out["skipped_text"] or ""
        if first_decision is not None:
            args = first_decision.get("args") or {}
            args_repr = ", ".join(f"{k}={v!r}" for k, v in list(args.items())[:2]) if isinstance(args, dict) else ""
            tool_activity = [f"  ▸ {first_decision['tool']}({args_repr})"]
        else:
            tool_activity = []
    else:
        text = (result.output if hasattr(result, "output") else str(result)) or ""
        text = text.strip()
        tool_activity, walked = _walk_new_messages(result)
        first_decision = first_decision or walked
    spoke_via_tool = any("🔊" in line for line in tool_activity)

    write_log({
        "user": user_text, "session_key": key, "answer": text,
        "tool_calls": len(tool_activity), "tool_activity": tool_activity,
        "decision": first_decision, "skipped_final": skipped,
        "latency": {"total": elapsed, "voice": True},
    })

    if _pipeline["with_memory"] and history is not None:
        if skipped:
            history.extend(iter_out["skipped_msgs"])
        else:
            try:
                new_msgs = result.new_messages() if hasattr(result, "new_messages") else result.all_messages()
            except Exception:
                new_msgs = []
            history.extend(new_msgs)
        overflow = len(history) - _MAX_HISTORY_MESSAGES
        if overflow > 0:
            del history[:overflow]

    runner = _pipeline["thinking_runner"]
    if runner is not None:
        runner.queue(user_text, run_id=os.environ.get("BENCH_RUN_ID"))

    return {
        "text": text, "tool_activity": tool_activity,
        "spoke_via_tool": spoke_via_tool, "elapsed_s": elapsed,
        "skipped_final": skipped,
    }


def init_extensions(args: Any, client: Any) -> None:
    """Wire up memory / MCP / thinking based on CLI flags + env vars.
    Mirrors python_pydantic_ai.init_extensions."""
    with_memory = getattr(args, "with_memory", False) or os.environ.get("JAEGER_WITH_MEMORY") == "1"
    with_mcp = getattr(args, "with_mcp", False) or os.environ.get("JAEGER_WITH_MCP") == "1"
    with_thinking = getattr(args, "think", False) or os.environ.get("JAEGER_WITH_THINKING") == "1"

    _pipeline["with_memory"] = with_memory
    _pipeline["with_mcp"] = with_mcp
    _pipeline["with_thinking"] = with_thinking
    _pipeline["client"] = client

    if with_mcp:
        try:
            from .plugins.mcp import client as mcp_client
            registry = mcp_client.init_from_config()
            specs = registry.list_tools()
            _pipeline["mcp_specs"] = specs
            if specs:
                print(f"[jaeger] MCP enabled with {len(specs)} extended tool(s).", flush=True)
        except Exception as exc:
            print(f"[jaeger] --with-mcp failed: {exc}", file=sys.stderr, flush=True)

    if with_thinking:
        try:
            from .core.runners import thinking_runner
            lock = _pipeline.get("llm_lock") or threading.Lock()
            _pipeline["llm_lock"] = lock
            # Per-instance log path keeps thinking output out of the framework
            # source tree (matches the vocabulary contract — runners log into
            # <instance>/logs/, not into core/).
            layout = _pipeline.get("layout")
            log_path = (layout.logs_dir / "thinking.jsonl") if layout is not None else None
            _pipeline["thinking_runner"] = thinking_runner.ThinkingRunner(
                client, "jaeger_os", lock, _pipeline["system_prompt"],
                log_path=log_path,
            )
            print("[jaeger] background thinking enabled — see <instance>/logs/thinking.jsonl.", flush=True)
        except Exception as exc:
            print(f"[jaeger] --think failed: {exc}", file=sys.stderr, flush=True)


def shutdown_extensions(wait: bool = True) -> None:
    """Drain any background thinking jobs before tear-down."""
    runner = _pipeline["thinking_runner"]
    if runner is not None:
        if runner.pending() > 0:
            print("[jaeger] waiting for background thinking jobs...", flush=True)
        runner.shutdown(wait=wait)


# ---------------------------------------------------------------------------
# Llama-cpp-python client shim
# ---------------------------------------------------------------------------
@dataclass
class _ChatResult:
    """Minimal completion shape ThinkingRunner expects."""
    text: str
    latency_s: float
    ttft_s: float = 0.0



class LlamaCppPythonClient:
    """Loads a Llama instance once and exposes `.model` (a LlamaCppModel)
    for the agent loop plus `.chat()` for the bounded finalize passes.

    This is the local-first default brain. The opt-in alternative is
    :class:`jaeger_os.core.external_model.ExternalModelClient`, which
    presents the same `.model` / `.chat()` / `.kind` surface."""

    kind = "local"

    @property
    def model(self) -> "LlamaCppModel":
        """Fresh LlamaCppModel over the resident Llama. ``build_agent``
        calls this once per agent build; each agent gets its own wrapper
        but they share the one loaded weights. The model name is passed
        through so the wrapper can pick the right native tool dialect
        (Gemma 4 vs. Qwen3)."""
        return LlamaCppModel(self.llm, model_name=getattr(self, "model_name", "local-gemma-4"))

    def describe(self) -> str:
        return f"local · llama-cpp · {getattr(self, 'model_name', '?')}"

    def __init__(self, model_cfg: Any, warmup: bool = True) -> None:
        from llama_cpp import Llama

        from .core.model_resolver import resolve_model_path
        # Resolve through the registry so configs can carry a stable
        # name like "gemma-4-26b-a4b-it-q4_k_m" instead of a fragile
        # absolute path. Downloads from HF Hub on first use if the
        # file isn't in ~/.jaeger/models/ or ./models/.
        resolved = resolve_model_path(model_cfg.model_path)
        path = Path(resolved)
        if not path.exists():
            raise FileNotFoundError(f"Model file not found: {path}")
        self.model_name = path.name
        kwargs: dict[str, Any] = {
            "model_path": str(path),
            "n_ctx": model_cfg.ctx,
            "n_gpu_layers": model_cfg.gpu_layers,
            "n_batch": model_cfg.n_batch,
            "n_ubatch": model_cfg.n_ubatch,
            "flash_attn": model_cfg.flash_attn,
            "verbose": False,
        }
        if model_cfg.threads is not None:
            kwargs["n_threads"] = model_cfg.threads
        print(f"[jaeger] loading {path.name}...", flush=True)
        started = time.perf_counter()
        self.llm = Llama(**kwargs)
        print(f"[jaeger] loaded in {time.perf_counter() - started:.1f}s.", flush=True)
        if warmup:
            self.llm.create_chat_completion(
                messages=[{"role": "user", "content": "hi"}],
                max_tokens=1, temperature=0.0,
            )

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        max_tokens: int = 512,
        temperature: float = 0.0,
        top_p: float = 0.95,
        stream: bool = False,
        grammar: str | None = None,
        tools: list[dict[str, Any]] | None = None,
    ) -> _ChatResult:
        """Minimal chat completion wrapper (ThinkingRunner, _fast_finalize).
        Ignores `stream` and `grammar`. Returns text + wall-clock latency.

        Pass ``tools`` to render the SAME ``<system + tools>`` prompt
        prefix the agent's decide call uses — that keeps the tool-schema
        KV cache resident across decide/finalize instead of evicting it
        (a system-only finalize forces the next decide to cold-prefill
        all ~60 tool schemas, ~12s)."""
        started = time.perf_counter()
        kwargs: dict[str, Any] = {
            "messages": messages, "max_tokens": max_tokens,
            "temperature": temperature, "top_p": top_p, "stream": False,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"
        completion = self.llm.create_chat_completion(**kwargs)
        elapsed = time.perf_counter() - started
        text = completion["choices"][0]["message"].get("content") or ""
        return _ChatResult(text=text.strip(), latency_s=elapsed)


def make_client(config: Any, layout: Any = None, *, warmup: bool = True) -> Any:
    """Build the agent's brain client for ``config``.

    Local-first: returns a :class:`LlamaCppPythonClient` unless
    ``config.external_model.enabled`` is set, in which case the agent
    runs on the configured external provider (LM Studio / OpenAI /
    Anthropic). If the external client can't be built or reached, this
    prints a warning and falls back to the local model — the robot is
    never left without a brain because a cloud endpoint is down."""
    ext = getattr(config, "external_model", None)
    if ext is not None and getattr(ext, "enabled", False):
        from .core.external_model import ExternalModelClient, ExternalModelError
        try:
            client = ExternalModelClient(ext, layout)
            check = client.connectivity_check()
            if not check["ok"]:
                print(f"[jaeger] external model unreachable ({check['detail']}); "
                      "falling back to the local model.", flush=True)
            else:
                print(f"[jaeger] external model: {client.describe()} "
                      f"(reachable, {check['latency_s']}s)", flush=True)
                return client
        except ExternalModelError as exc:
            print(f"[jaeger] external model not configured ({exc}); "
                  "falling back to the local model.", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"[jaeger] external model error ({type(exc).__name__}: {exc}); "
                  "falling back to the local model.", flush=True)
    return LlamaCppPythonClient(config.model, warmup=warmup)


# ---------------------------------------------------------------------------
# CLI loop with slash commands + multi-line paste detection
# ---------------------------------------------------------------------------
HELP_BANNER = """\
Commands (type at the You: prompt):
  /help              show this help
  /latency [on|off]  toggle the per-turn latency breakdown
  /tools [on|off]    toggle the tool-activity lines under each reply
  /setup             re-run the setup wizard (backs up the current instance)
  /skills            list registered skills
  /instances         list all instances (read-only; mutate via CLI flags)
  /whoami            show the active instance + identity
  /multi             enter multi-line mode (finish with a blank line)
  /quit              exit (also: exit, quit, Ctrl-D)

Pasting multiple lines is auto-detected — paste freely, the whole block
is sent as one turn.
"""


def _print_help() -> None:
    print(HELP_BANNER, end="", flush=True)


def _read_user_input(prompt_text: str = "You: ") -> str | None:
    try:
        first = input(prompt_text)
    except (EOFError, KeyboardInterrupt):
        return None
    if first.strip() == "/multi":
        print("(multi-line mode — finish with a blank line)")
        lines: list[str] = []
        while True:
            try:
                line = input("... ")
            except (EOFError, KeyboardInterrupt):
                break
            if line == "":
                break
            lines.append(line)
        return "\n".join(lines).strip()
    try:
        extra: list[str] = []
        while sys.stdin in select.select([sys.stdin], [], [], 0.03)[0]:
            line = sys.stdin.readline()
            if line == "":
                break
            extra.append(line.rstrip("\n"))
        if extra:
            return "\n".join([first, *extra]).strip()
    except Exception:
        pass
    return first.strip()


def _handle_slash(cmd: str, client: Any | None) -> bool:
    parts = cmd.split()
    head = parts[0].lower()
    arg = parts[1].lower() if len(parts) > 1 else ""
    if head in {"/quit", "/exit"}:
        return False
    if head == "/help":
        _print_help()
        return True
    if head == "/latency":
        _pipeline["show_latency"] = (arg == "on") if arg in {"on", "off"} else not _pipeline.get("show_latency")
        print(f"  latency report → {'on' if _pipeline['show_latency'] else 'off'}")
        return True
    if head == "/tools":
        _pipeline["show_tool_activity"] = (arg == "on") if arg in {"on", "off"} else not _pipeline.get("show_tool_activity")
        print(f"  tool activity → {'on' if _pipeline['show_tool_activity'] else 'off'}")
        return True
    if head == "/skills":
        from .core.skill_loader import discover_skills
        for s in discover_skills(_pipeline["layout"]):
            print(f"  {s.zone:8s}  {s.name}_v{s.version}  ({s.module_path})")
        return True
    if head == "/setup":
        try:
            new_layout = run_wizard(force=True, instance_name=_pipeline["config"].instance_name)
            print(f"  setup complete — restart Jaeger to pick up changes at {new_layout.root}.")
        except Exception as exc:
            print(f"  /setup failed: {exc}")
        return True
    if head in {"/instances", "/list-instances"}:
        # Read-only — mutation ops live on the CLI (--create/delete/clear)
        # and require restart since we'd otherwise have to tear down the
        # already-loaded LLM + instance lock.
        _cli_list_instances()
        return True
    if head == "/whoami":
        layout: InstanceLayout = _pipeline["layout"]
        cfg = _pipeline.get("config")
        print(f"  instance: {cfg.instance_name if cfg else '?'}")
        print(f"  path:     {layout.root}")
        try:
            from .core.schemas import Identity, load_yaml
            ident = load_yaml(layout.identity_path, Identity)
            print(f"  identity: {ident.name!r} — {ident.role}")
        except Exception as exc:
            print(f"  identity: (unreadable: {exc})")
        return True
    print(f"  unknown command: {head} (try /help)")
    return True


def cli_loop(client: Any) -> int:
    layout: InstanceLayout = _pipeline["layout"]
    print(f"[jaeger] Instance: {layout.root}")
    if _pipeline.get("show_help_on_start", True):
        _print_help()
    else:
        print("Type /help for commands. /quit to stop.")
    while True:
        text = _read_user_input("You: ")
        if text is None:
            print()
            return 0
        if not text:
            continue
        if text.lower() in {"exit", "quit"}:
            return 0
        if text.startswith("/"):
            if not _handle_slash(text, client):
                return 0
            continue
        run_command(client, text)


# ---------------------------------------------------------------------------
# Self-test (no LLM)
# ---------------------------------------------------------------------------
def self_test(layout: InstanceLayout) -> int:
    """Exercise the sandbox + memory + skill loader without touching the LLM."""
    jaeger_tools.bind(layout)
    print(f"[jaeger] self-test against {layout.root}")
    checks: list[tuple[str, Any]] = [
        ("get_time", lambda: jaeger_tools.get_time()),
        ("calculate", lambda: jaeger_tools.calculate("(2+3)*4")),
        ("system_status", lambda: jaeger_tools.system_status()),
        ("write_file (allowed)", lambda: jaeger_tools.file_write("self_test/hello.txt", "hello jaeger")),
        ("read_file (allowed)",  lambda: jaeger_tools.file_read("skills/self_test/hello.txt")),
        ("write_file (.. escape rejected)", lambda: jaeger_tools.file_write("../identity.yaml", "bad")),
        ("write_file (absolute path rejected)", lambda: jaeger_tools.file_write("/etc/passwd", "bad")),
        ("read_file (credentials rejected)", lambda: jaeger_tools.file_read("credentials/anything")),
        ("remember/recall", lambda: (jaeger_tools.remember("k", "v"), jaeger_tools.recall("k"))),
        ("list_facts", lambda: jaeger_tools.list_facts()),
        ("forget", lambda: jaeger_tools.forget("k")),
        ("list_skill_dir", lambda: jaeger_tools.list_skill_dir(".")),
    ]
    fail = 0
    for label, fn in checks:
        try:
            result = fn()
        except Exception as exc:
            print(f"== {label} == FAILED: {exc}")
            fail += 1
            continue
        as_str = json.dumps(result, ensure_ascii=True, default=str)
        if len(as_str) > 140:
            as_str = as_str[:137] + "..."
        print(f"== {label} == {as_str}")
    # Sandbox negative-checks should have returned a dict with written=False / read=False
    # — confirm we got the rejection shape, not a stack trace.
    try:
        bad = jaeger_tools.file_write("../identity.yaml", "X")
        assert bad.get("written") is False, "sandbox failed to reject .. escape"
        bad2 = jaeger_tools.file_write("/etc/passwd", "X")
        assert bad2.get("written") is False, "sandbox failed to reject absolute path"
        bad3 = jaeger_tools.file_read("credentials/anything")
        assert bad3.get("read") is False, "sandbox failed to reject credentials read"
        print("== sandbox enforcement == OK (.. + abs path + credentials all rejected)")
    except AssertionError as exc:
        print(f"== sandbox enforcement == FAILED: {exc}")
        fail += 1

    # Skill discovery
    try:
        from .core.skill_loader import discover_skills
        discovered = discover_skills(layout)
        names = [f"{s.name}_v{s.version}({s.zone})" for s in discovered]
        print(f"== skill discovery == {names or '(none yet — core skills/ empty)'}")
    except Exception as exc:
        print(f"== skill discovery == FAILED: {exc}")
        fail += 1

    # Credentials: round-trip + perm enforcement
    try:
        creds.set_credential(layout, "self_test_token", "abc123")
        v = creds.get_credential(layout, "self_test_token")
        assert v == "abc123", f"value round-trip mismatch: {v!r}"
        path = layout.credentials_dir / "self_test_token"
        # Verify perms
        import stat as _stat
        mode = _stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600, f"expected 0o600, got {oct(mode)}"

        # Loosen perms and confirm refusal
        os.chmod(path, 0o644)
        try:
            creds.get_credential(layout, "self_test_token")
            raise AssertionError("get_credential should have refused on 0o644")
        except creds.CredentialError:
            pass
        os.chmod(path, 0o600)

        # Invalid name rejection
        try:
            creds.set_credential(layout, "../etc/passwd", "X")
            raise AssertionError("invalid name should have been rejected")
        except creds.CredentialError:
            pass

        creds.delete_credential(layout, "self_test_token")
        print("== credentials == OK (round-trip, perm enforcement, name validation)")
    except Exception as exc:
        print(f"== credentials == FAILED: {exc}")
        fail += 1

    # Migrations discovery
    try:
        from .core.migrations import discover_migrations
        migs = discover_migrations()
        print(f"== migrations == {[m['name'] for m in migs] or '(none registered — at head)'}")
    except Exception as exc:
        print(f"== migrations == FAILED: {exc}")
        fail += 1

    return 0 if fail == 0 else 1


# ---------------------------------------------------------------------------
# Credential CLI handlers
# ---------------------------------------------------------------------------
def _cli_set_credential(layout: InstanceLayout, name: str) -> int:
    """Read the value from stdin so it never appears in shell history.

    If stdin is a TTY, prompt with getpass (the value is echoed-suppressed).
    Otherwise read a single line from stdin (allows `echo $TOK | jaeger
    --set-credential NAME` for scripted setups; the user accepts that
    risk by piping).
    """
    import getpass
    if sys.stdin.isatty():
        try:
            value = getpass.getpass(f"Value for credential {name!r} (input hidden): ")
        except KeyboardInterrupt:
            print()
            return 2
    else:
        value = sys.stdin.readline().rstrip("\n")
    if not value:
        print("[jaeger] empty value — refusing to store.", file=sys.stderr, flush=True)
        return 2
    try:
        path = creds.set_credential(layout, name, value)
    except creds.CredentialError as exc:
        print(f"[jaeger] {exc}", file=sys.stderr, flush=True)
        return 2
    print(f"[jaeger] stored credential {name!r} at {path} (mode 0600).")
    return 0


def _cli_list_credentials(layout: InstanceLayout) -> int:
    names = creds.list_credentials(layout)
    if not names:
        print("(no credentials stored yet)")
        return 0
    print("Credentials in", layout.credentials_dir)
    for n in names:
        print(f"  {n}")
    return 0


def _cli_delete_credential(layout: InstanceLayout, name: str) -> int:
    try:
        existed = creds.delete_credential(layout, name)
    except creds.CredentialError as exc:
        print(f"[jaeger] {exc}", file=sys.stderr, flush=True)
        return 2
    if existed:
        print(f"[jaeger] deleted credential {name!r}.")
        return 0
    print(f"[jaeger] no credential named {name!r} to delete.")
    return 1


def _cli_migrate(layout: InstanceLayout) -> int:
    from .core.migrations import run_pending_migrations

    try:
        applied = run_pending_migrations(layout)
    except Exception as exc:
        print(f"[jaeger] migration failed: {exc}", file=sys.stderr, flush=True)
        return 2
    if not applied:
        print("[jaeger] instance is already at the installed core version — nothing to migrate.")
    else:
        print(f"[jaeger] applied {len(applied)} migration(s):")
        for name in applied:
            print(f"  ✓ {name}")
    return 0


# ---------------------------------------------------------------------------
# Instance management — admin commands. All exit after running and never
# enter the chat loop. Mutating ops (delete / clear) prompt for confirmation
# unless --force is passed (or stdin is not a TTY, where confirmation is
# auto-yes so scripts can run them in CI).
# ---------------------------------------------------------------------------
def _instance_root() -> "Path":
    """Parent directory containing all instances. Same resolution rules as
    a single instance, just without the trailing instance-name component."""
    # resolve_instance_dir("__probe__") is built deterministically from the
    # same parent. Strip the leaf to get the root.
    return resolve_instance_dir("__probe__").parent


def _list_instances() -> list[tuple[str, "Path", bool]]:
    """Return [(name, path, has_manifest), ...] for every directory under
    the instance root. has_manifest is True when the dir looks like a
    valid Jaeger instance (manifest.json present)."""
    root = _instance_root()
    if not root.exists():
        return []
    instances = []
    for child in sorted(root.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        has_manifest = (child / "manifest.json").exists()
        instances.append((child.name, child, has_manifest))
    return instances


def _cli_list_instances() -> int:
    """Print all instances under the root with their identity + status."""
    instances = _list_instances()
    root = _instance_root()
    print(f"Instances under {root}:")
    if not instances:
        print("  (none yet — run --setup or --create-instance to create one)")
        return 0
    current = default_instance_name()
    for name, path, has_manifest in instances:
        marker = " *" if name == current else "  "
        if has_manifest:
            # Try to read the instance's identity for a one-line summary.
            try:
                from .core.schemas import Identity, load_yaml
                identity = load_yaml(path / "identity.yaml", Identity)
                summary = f"{identity.name!r} — {identity.role}"
            except Exception:
                summary = "(unreadable identity.yaml)"
        else:
            summary = "(stub: no manifest.json — partial setup?)"
        print(f"{marker} {name:<24} {summary}")
    print(f"\n* = current (JAEGER_INSTANCE_NAME={current!r})")
    return 0


def _cli_create_instance(name: str, *, force: bool = False) -> int:
    """Non-interactively create a new instance with default identity + config.
    Refuses if the target dir already exists (use --force to overwrite)."""
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if layout.root.exists() and any(layout.root.iterdir()):
        if not force:
            print(f"[jaeger] instance {name!r} already exists at {layout.root} "
                  f"— use --force to overwrite, or pick a different name.",
                  file=sys.stderr, flush=True)
            return 2
        # Overwrite path
        import shutil
        shutil.rmtree(layout.root, ignore_errors=True)

    from .core.schemas import (
        Config, DisplayConfig, Identity, Manifest, ModelConfig, SkillsConfig,
        dump_json, dump_yaml,
    )
    from .core.model_resolver import DEFAULT_MODEL

    layout.root.mkdir(parents=True, exist_ok=True)
    layout.ensure_dirs()
    dump_yaml(layout.identity_path, Identity(
        name=name.capitalize(),
        role="local AI assistant",
        personality=(
            "Concise and direct. Match tool calls to user intent — never "
            "free-text when a tool exists for the request."
        ),
    ))
    dump_yaml(layout.config_path, Config(
        instance_name=name,
        # Store the registry NAME, not a resolved absolute path —
        # ``LlamaCppPythonClient`` resolves through ``model_resolver``
        # at boot, which auto-downloads from HF Hub if the file isn't
        # in the user cache. Survives moves / new machines unchanged.
        model=ModelConfig(model_path=DEFAULT_MODEL),
        display=DisplayConfig(show_help_on_start=False),
        skills=SkillsConfig(run_smoke_tests=True),
    ))
    dump_json(layout.manifest_path, Manifest(instance_name=name))
    print(f"[jaeger] created instance {name!r} at {layout.root}")
    print(f"         identity.yaml + config.yaml + manifest.json populated with defaults.")
    print(f"         edit identity.yaml / config.yaml to customize, then launch with:")
    print(f"           python -m jaeger_os --instance {name}")
    return 0


def _cli_delete_instance(name: str, *, force: bool = False) -> int:
    """Remove an entire instance directory. PROMPTS for confirmation unless
    --force. Refuses to delete the currently-active instance (per
    JAEGER_INSTANCE_NAME) without --force as a sanity check."""
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.root.exists():
        print(f"[jaeger] no instance {name!r} at {layout.root} — nothing to delete.")
        return 1

    if name == default_instance_name() and not force:
        print(f"[jaeger] {name!r} is the active instance (per JAEGER_INSTANCE_NAME). "
              f"Pass --force to delete it anyway.", file=sys.stderr, flush=True)
        return 2

    if not force:
        if sys.stdin.isatty():
            confirm = input(
                f"[jaeger] delete instance {name!r} at {layout.root}? "
                f"This is irreversible. Type the instance name to confirm: "
            )
            if confirm.strip() != name:
                print("[jaeger] aborted (name didn't match).")
                return 1
        # If stdin isn't a TTY (piped/scripted), require --force explicitly.
        else:
            print(f"[jaeger] non-interactive delete refused; pass --force.", file=sys.stderr)
            return 2

    import shutil
    shutil.rmtree(layout.root)
    print(f"[jaeger] deleted instance {name!r}.")
    return 0


def _cli_clear_instance(name: str, *, force: bool = False) -> int:
    """Reset memory + logs but keep identity / config / manifest / credentials /
    skills. Useful for 'start a clean conversation, don't blow away your setup.'
    """
    layout = InstanceLayout(root=resolve_instance_dir(name))
    if not layout.root.exists():
        print(f"[jaeger] no instance {name!r} at {layout.root} — nothing to clear.")
        return 1

    if not force:
        if sys.stdin.isatty():
            confirm = input(
                f"[jaeger] clear memory + logs for instance {name!r}? "
                f"(identity / config / credentials / skills are preserved) [y/N]: "
            )
            if confirm.strip().lower() not in ("y", "yes"):
                print("[jaeger] aborted.")
                return 1
        else:
            print(f"[jaeger] non-interactive clear refused; pass --force.", file=sys.stderr)
            return 2

    import shutil
    cleared = []
    # Memory: wipe everything (facts.json, episodic.jsonl, embeddings.npz, …)
    if layout.memory_dir.exists():
        for entry in layout.memory_dir.iterdir():
            try:
                if entry.is_file():
                    entry.unlink()
                else:
                    shutil.rmtree(entry, ignore_errors=True)
            except Exception as exc:
                print(f"[jaeger] couldn't clear {entry}: {exc}", file=sys.stderr)
        cleared.append("memory/")
    # Logs: drop everything (latency, audit, thinking)
    if layout.logs_dir.exists():
        for entry in layout.logs_dir.iterdir():
            try:
                if entry.is_file():
                    entry.unlink()
                else:
                    shutil.rmtree(entry, ignore_errors=True)
            except Exception as exc:
                print(f"[jaeger] couldn't clear {entry}: {exc}", file=sys.stderr)
        cleared.append("logs/")
    print(f"[jaeger] cleared {name!r}: {', '.join(cleared) or '(nothing to clear)'}")
    print(f"         preserved: identity.yaml, config.yaml, manifest.json, credentials/, skills/")
    return 0


# ---------------------------------------------------------------------------
# CLI argparse + main
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Jaeger: self-improving local agent.")
    p.add_argument("prompt", nargs="*", help="Optional one-shot command.")
    p.add_argument("--instance", type=str, default=None,
                   help="Instance name (default: JAEGER_INSTANCE_NAME or 'default').")
    p.add_argument("--setup", action="store_true",
                   help="Run (or re-run) the setup wizard, then exit.")
    p.add_argument("--self-test", action="store_true",
                   help="Run the sandbox/memory/skill smoke tests without loading the LLM.")
    p.add_argument("--doctor", action="store_true",
                   help="Check that every dependency + system library is ready, then exit.")
    p.add_argument("--no-warmup", action="store_true", help="Skip llama-cpp warmup.")
    p.add_argument("--no-cron", action="store_true", help="Don't start the cron runner.")
    p.add_argument("--set-credential", metavar="NAME",
                   help="Store a credential under this name (value read from stdin), then exit.")
    p.add_argument("--list-credentials", action="store_true",
                   help="List stored credential names (values never printed) and exit.")
    p.add_argument("--delete-credential", metavar="NAME",
                   help="Delete a stored credential by name and exit.")
    p.add_argument("--migrate", action="store_true",
                   help="Run any pending core migrations against this instance and exit.")
    p.add_argument("--list-instances", action="store_true",
                   help="List every instance under the root and exit.")
    p.add_argument("--create-instance", metavar="NAME",
                   help="Non-interactively create a new instance with default identity + config, then exit.")
    p.add_argument("--delete-instance", metavar="NAME",
                   help="Delete an instance directory and exit. Prompts for confirmation unless --force.")
    p.add_argument("--clear-instance", metavar="NAME",
                   help="Clear memory + logs for an instance (preserves identity / config / credentials / skills). Prompts unless --force.")
    p.add_argument("--force", action="store_true",
                   help="Skip confirmation prompts on destructive commands (delete-instance / clear-instance / create-instance overwrite).")
    p.add_argument("--with-memory", action="store_true",
                   help=("Carry conversation history across turns (load last 5 "
                         "episodic turns + accumulate within session). Auto-on "
                         "in interactive mode; off for one-shot/bench runs."))
    p.add_argument("--with-mcp", action="store_true",
                   help=("Connect to MCP servers from plugins/mcp_config.json "
                         "and expose their tools through the agent surface."))
    p.add_argument("--think", action="store_true",
                   help=("Run a background chain-of-thought call after each "
                         "user turn. Logs to plugins/thinking.jsonl. Shares the "
                         "main LLM lock so it never decodes concurrently."))
    p.add_argument("--voice", action="store_true",
                   help=("Launch the voice loop daemon instead of CLI chat. "
                         "All flags after --voice are forwarded to voice_loop "
                         "(--stt-mode, --barge-in, --no-aec, --require-wake-word, "
                         "--no-chimes, --fast-model, --accurate-model). "
                         "See `python -m jaeger_os --voice --help` for the "
                         "voice flag surface."))
    p.add_argument("--daemon", action="store_true",
                   help=("Run headless: boot the pipeline, start the cron "
                         "runner, and work the Deep Think queue in the "
                         "background. No TUI, no interactive input. Runs "
                         "until SIGTERM/SIGINT. See deploy/ for the launchd "
                         "plist."))
    return p.parse_args()


@dataclass
class TUIBootResult:
    """Returned from :func:`boot_for_tui`. ``cleanup`` releases the
    instance lock + shuts down extensions; call it from the TUI's
    finally block."""

    client: Any
    layout: InstanceLayout
    cleanup: Any  # Callable[[], None]


def boot_for_tui(
    *,
    instance_name: str | None = None,
    with_memory: bool = True,
    warmup: bool = True,
) -> TUIBootResult:
    """Boot the jaeger pipeline for an interactive TUI session.

    Mirrors the subset of :func:`main` that ``cli_loop`` needs:
    instance resolve → manifest gate → lock → bind tools → load model
    → build agent → prewarm. Returns the client (for
    :func:`run_command`) and a cleanup callable.

    The TUI doesn't use the cron runner, MCP plugins, or thinking
    extensions — keeping the surface small so the boot is fast and
    the failure modes match ``cli_loop`` 1:1.
    """
    instance_name = instance_name or default_instance_name()
    root = resolve_instance_dir(instance_name)
    layout = InstanceLayout(root=root)

    if not layout.exists():
        layout = run_wizard(force=False, instance_name=instance_name)

    try:
        manifest = check_manifest(layout)
    except CoreVersionMismatch:
        from .core.migrations import run_pending_migrations
        run_pending_migrations(layout)
        manifest = check_manifest(layout)

    lock = InstanceLock(layout)
    lock.acquire()

    try:
        jaeger_tools.bind(layout)
        touch_manifest_started(layout, manifest)

        config: Config = load_yaml(layout.config_path, Config)
        _pipeline["layout"] = layout
        _pipeline["config"] = config
        _pipeline["show_latency"] = config.display.show_latency
        _pipeline["show_tool_activity"] = config.display.show_tool_activity
        _pipeline["show_help_on_start"] = False
        _pipeline["system_prompt"] = prompt_module.build_system_prompt(layout)
        _pipeline["with_memory"] = with_memory

        # Wire the interactive permission provider so tier-gated tools
        # (run_in_venv, install_package, …) prompt the user instead of
        # being auto-denied. On non-interactive stdin it denies safely.
        _preflight_log()
        install_policy(PermissionPolicy(confirmation=_confirmation_provider(config, layout)))

        client = make_client(config, layout, warmup=warmup)
        _get_agent(client)
        if warmup:
            prewarm(client)
            warm_plugins(config)

        llm_lock = threading.Lock()
        _pipeline["llm_lock"] = llm_lock
    except Exception:
        lock.release()
        raise

    def cleanup() -> None:
        try:
            shutdown_extensions(wait=False)
        except Exception:
            pass
        try:
            lock.release()
        except Exception:
            pass

    return TUIBootResult(client=client, layout=layout, cleanup=cleanup)


def switch_model(new_model: str, *, warmup: bool = True) -> Any:
    """Swap the resident LLM to a different model — SAME instance.

    Phase-0 of Deep Think (see docs/deep_think_design.md). The mode
    manager calls this to swap Realtime ⇄ Deep-Think models: unload the
    current model, load ``new_model``, rebuild the agent. The instance,
    layout, lock, tools, and memory all stay bound — only the model and
    its agent change.

    ``new_model`` is a model_resolver registry name (e.g.
    ``qwen3-coder-30b-a3b-q4_k_m``) or a path; it resolves through
    :func:`model_resolver.resolve_model_path`.

    IMPORTANT — RAM: the caller MUST drop its reference to the OLD
    client before calling this. On a unified-memory Mac, holding both
    references means both model weights are briefly co-resident, which
    can OOM a 32 GB machine. This function nulls ``_pipeline["client"]``
    and forces a GC before allocating the new model, but it cannot
    reach the caller's own variable — drop it on your side first.

    Returns the new client.
    """
    import gc

    config = _pipeline.get("config")
    if config is None:
        raise RuntimeError("switch_model: no active pipeline — boot first.")

    # Model swap is a llama-cpp feature — it unloads/loads GGUF weights.
    # When the brain is an external model there is nothing local to swap;
    # Deep Think keeps running on that same external model.
    ext = getattr(config, "external_model", None)
    if ext is not None and getattr(ext, "enabled", False):
        existing = _pipeline.get("client")
        if existing is not None:
            return existing
        return make_client(config, _pipeline.get("layout"), warmup=warmup)

    # New ModelConfig: identical tuning (ctx, gpu_layers, …), new model.
    new_model_cfg = config.model.model_copy(update={"model_path": new_model})

    # Drop the old model so llama-cpp frees its weights BEFORE we
    # allocate the new one. _agent_cache holds the old agent (which
    # references the old client/model) — clear it too.
    _pipeline["client"] = None
    _agent_cache.clear()
    gc.collect()

    client = LlamaCppPythonClient(new_model_cfg, warmup=warmup)
    _get_agent(client)            # rebuilds the agent + reloads skills
    if warmup:
        prewarm(client)

    # Persist so subsequent reads see the active model.
    config.model = new_model_cfg
    _pipeline["client"] = client
    return client


def run_daemon(*, instance_name: str | None = None,
               poll_seconds: int = 60) -> int:
    """Headless daemon: boot the pipeline, start the cron runner, and
    work the Deep Think queue in the background.

    No TUI, no interactive input. Runs until SIGTERM/SIGINT. Intended
    to run under launchd (see deploy/) so the robot operates
    unattended. Output goes to stdout — launchd redirects it to a log.
    """
    import signal as _signal

    from .core.deep_think import queue_for_layout
    from .core.model_resolver import DEFAULT_CODER_MODEL, DEFAULT_MODEL
    from .core.reflection import reflect_on_task, save_reflection

    print("[jaeger-daemon] booting…", flush=True)
    boot = boot_for_tui(instance_name=instance_name, with_memory=True,
                        warmup=True)
    layout = boot.layout
    queue = queue_for_layout(layout)

    _stop = {"flag": False}

    def _on_signal(signum: int, _frame: Any) -> None:
        print(f"[jaeger-daemon] signal {signum} — shutting down…", flush=True)
        _stop["flag"] = True

    _signal.signal(_signal.SIGTERM, _on_signal)
    _signal.signal(_signal.SIGINT, _on_signal)

    # Cron runner — scheduled prompts fire on the shared llm_lock.
    cron = None
    try:
        llm_lock = _pipeline.get("llm_lock")

        def _cron_cb(prompt: str, session_key: str | None = None) -> None:
            run_command(boot.client, prompt, session_key=session_key)

        cron = CronRunner(_cron_cb, llm_lock=llm_lock)
        cron.start()
        print("[jaeger-daemon] cron runner started.", flush=True)
    except Exception as exc:  # noqa: BLE001
        print(f"[jaeger-daemon] cron runner skipped: {exc}", flush=True)

    print(f"[jaeger-daemon] ready — polling every {poll_seconds}s. "
          "Ctrl-C / SIGTERM to stop.", flush=True)
    client = boot.client
    try:
        while not _stop["flag"]:
            task = queue.next_pending()
            if task is not None:
                # There's approved work — swap to the coder model, drain
                # the queue, swap back. Same shape as the TUI's Deep
                # Think loop, headless.
                print(f"[jaeger-daemon] Deep Think: {queue.summary()}",
                      flush=True)
                try:
                    client = switch_model(DEFAULT_CODER_MODEL)
                except Exception as exc:  # noqa: BLE001
                    print(f"[jaeger-daemon] coder model load failed: {exc}",
                          flush=True)
                    client = switch_model(DEFAULT_MODEL)
                    time.sleep(poll_seconds)
                    continue
                while not _stop["flag"]:
                    task = queue.next_pending()
                    if task is None:
                        break
                    queue.mark_in_progress(task.id)
                    print(f"[jaeger-daemon] working {task.id}: "
                          f"{task.description}", flush=True)
                    outcome = "done"
                    try:
                        run_command(
                            client,
                            f"Deep Think task — complete it fully, writing "
                            f"files into skills/ and installing deps as "
                            f"needed:\n\n{task.description}",
                            session_key=f"daemon_{task.id}",
                        )
                        queue.mark_done(task.id, "completed by daemon")
                    except Exception as exc:  # noqa: BLE001
                        outcome = f"failed: {exc}"
                        queue.mark_failed(task.id, str(exc))
                    try:
                        refl = reflect_on_task(client, task.description, outcome)
                        if refl:
                            save_reflection(layout, task.description,
                                            outcome, refl)
                    except Exception:  # noqa: BLE001
                        pass
                # Swap the realtime model back in for cron / messaging.
                try:
                    client = switch_model(DEFAULT_MODEL)
                except Exception as exc:  # noqa: BLE001
                    print(f"[jaeger-daemon] realtime reload failed: {exc}",
                          flush=True)
            # Idle wait — short sleeps so a stop signal is responsive.
            slept = 0
            while slept < poll_seconds and not _stop["flag"]:
                time.sleep(min(2, poll_seconds - slept))
                slept += 2
    finally:
        if cron is not None:
            try:
                cron.shutdown(wait=False)
            except Exception:  # noqa: BLE001
                pass
        try:
            boot.cleanup()
        except Exception:  # noqa: BLE001
            pass
    print("[jaeger-daemon] stopped.", flush=True)
    return 0


def main() -> int:
    # If --voice is present, peel it off and delegate to the voice_loop
    # daemon. Voice_loop has its own argparse for STT mode, barge-in, AEC,
    # wake-word, chimes, model names, etc. — every flag the user types
    # after --voice flows through unchanged.
    if "--voice" in sys.argv[1:]:
        sys.argv.remove("--voice")
        from .plugins.voice_loop import main as voice_main
        return voice_main()
    # --tui launches the rich TUI. Peel it off and delegate to the TUI
    # entry point (which handles --instance / --banner-only) — same
    # pattern as --voice. This is what `jaeger-os --tui` resolves to.
    if "--tui" in sys.argv[1:]:
        sys.argv.remove("--tui")
        from .interfaces.tui.__main__ import main as tui_main
        return tui_main()
    args = parse_args()
    # --doctor: verify every dependency + system library, offer to
    # install whatever is missing, then exit. Needs no instance/model.
    if getattr(args, "doctor", False):
        from .core.preflight import (
            check_environment, fixable, format_report, install_missing, missing,
        )
        checks = check_environment()
        print(format_report(checks))
        cmds = fixable(checks)
        if cmds and sys.stdin.isatty():
            print("  These can be installed for you:")
            for cmd in cmds:
                print(f"    {' '.join(cmd)}")
            try:
                ans = input("  Install them now? [y/N]: ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                ans = ""
            if ans.startswith("y"):
                print()
                checks = install_missing(checks)
                print(format_report(checks))
                if missing(checks):
                    print("  Anything still missing may just need a restart to "
                          "register — re-run `jaeger-os --doctor` to confirm.")
        return 1 if missing(checks) else 0
    # Headless daemon mode — boot, cron, work the Deep Think queue.
    if getattr(args, "daemon", False):
        return run_daemon(instance_name=args.instance)
    instance_name = args.instance or default_instance_name()
    root = resolve_instance_dir(instance_name)
    layout = InstanceLayout(root=root)

    # Instance management commands — run BEFORE the wizard / manifest check,
    # since they're admin ops that don't require an active instance.
    if args.list_instances:
        return _cli_list_instances()
    if args.create_instance:
        return _cli_create_instance(args.create_instance, force=args.force)
    if args.delete_instance:
        return _cli_delete_instance(args.delete_instance, force=args.force)
    if args.clear_instance:
        return _cli_clear_instance(args.clear_instance, force=args.force)

    # Self-test runs without identity/config/manifest — it only exercises
    # the framework code paths (sandbox, memory, skill loader, credentials,
    # migration discovery). Skip the wizard and just create the subdirs.
    if args.self_test:
        layout.root.mkdir(parents=True, exist_ok=True)
        layout.ensure_dirs()
        return self_test(layout)

    if args.setup or not layout.exists():
        layout = run_wizard(force=args.setup, instance_name=instance_name)

    # Manifest gate. On version mismatch try the migration runner; only
    # refuse-to-start if migrations don't bring us to parity.
    try:
        manifest = check_manifest(layout)
    except CoreVersionMismatch:
        try:
            from .core.migrations import run_pending_migrations
            applied = run_pending_migrations(layout)
            if applied:
                print(f"[jaeger] applied {len(applied)} migration(s) to reach core {CORE_VERSION}: "
                      + ", ".join(applied), flush=True)
            manifest = check_manifest(layout)  # must pass now
        except Exception as exc:
            print(f"[jaeger] refuse-to-start: {exc}", file=sys.stderr, flush=True)
            return 2

    # Lock
    lock = InstanceLock(layout)
    try:
        lock.acquire()
    except RuntimeError as exc:
        print(f"[jaeger] {exc}", file=sys.stderr, flush=True)
        return 2

    try:
        # Bind tools/memory + record start time on the manifest
        jaeger_tools.bind(layout)
        touch_manifest_started(layout, manifest)

        # Credential management — these subcommands skip model load.
        if args.set_credential:
            return _cli_set_credential(layout, args.set_credential)
        if args.list_credentials:
            return _cli_list_credentials(layout)
        if args.delete_credential:
            return _cli_delete_credential(layout, args.delete_credential)
        if args.migrate:
            return _cli_migrate(layout)

        # NB: --self-test runs earlier in main() (before wizard / manifest / lock)
        # so it works against a brand-new install with no identity yet.

        config: Config = load_yaml(layout.config_path, Config)
        _pipeline["layout"] = layout
        _pipeline["config"] = config
        _pipeline["show_latency"] = config.display.show_latency
        _pipeline["show_tool_activity"] = config.display.show_tool_activity
        _pipeline["show_help_on_start"] = config.display.show_help_on_start
        _pipeline["system_prompt"] = prompt_module.build_system_prompt(layout)

        # Log rotation at startup — idempotent, never blocks the boot.
        try:
            rep = log_rotation.rotate_now(layout, config.retention)
            if rep["rotated"] or rep["pruned_by_age"] or rep["pruned_by_size"]:
                print(f"[jaeger] log rotation: rotated={rep['rotated']} "
                      f"pruned_age={rep['pruned_by_age']} "
                      f"pruned_size={rep['pruned_by_size']}", flush=True)
        except Exception as exc:
            print(f"[jaeger] log rotation skipped: {exc}", flush=True)

        # Interactive permission provider — tier-gated tools prompt the
        # user rather than auto-denying. Safe on non-interactive stdin.
        _preflight_log()
        install_policy(PermissionPolicy(confirmation=_confirmation_provider(config, layout)))

        client = make_client(config, layout, warmup=not args.no_warmup)
        # Force agent build now so skills load before the first prompt.
        _get_agent(client)
        # Prewarm KV cache (system prompt + tool schema) so the first
        # user-facing turn isn't cold. Same trick python_pydantic_ai uses.
        if not args.no_warmup:
            prewarm(client)
            warm_plugins(config)

        # Cron runner: same llm_lock the chat loop uses, so a scheduled
        # prompt firing mid-conversation serializes cleanly.
        llm_lock = threading.Lock()
        _pipeline["llm_lock"] = llm_lock
        cron_runner: CronRunner | None = None
        if not args.no_cron:
            def _cron_callback(prompt: str, session_key: str | None = None) -> None:
                run_command(client, prompt, session_key=session_key)

            def _daily_housekeeping() -> None:
                try:
                    rep = log_rotation.rotate_now(layout, config.retention)
                    if rep["rotated"] or rep["pruned_by_age"] or rep["pruned_by_size"]:
                        print(f"[jaeger-cron] housekeeping: {rep}", flush=True)
                except Exception as exc:
                    print(f"[jaeger-cron] housekeeping skipped: {exc}", flush=True)

            cron_runner = CronRunner(
                _cron_callback, llm_lock=llm_lock,
                housekeeping=_daily_housekeeping,
            )
            cron_runner.start()

        prompt = " ".join(args.prompt).strip()
        # Interactive chat assumes the user wants the conversation to remember
        # itself across turns. One-shot / bench runs default to off so the
        # MANDATORY rules at the top of the system prompt aren't diluted by
        # accumulated history. Explicit --with-memory always wins.
        with_memory = bool(args.with_memory) or os.environ.get("JAEGER_WITH_MEMORY") == "1"
        if not prompt and not with_memory:
            with_memory = True
        # Patch args so init_extensions picks up the resolved value
        args.with_memory = with_memory

        # Wire MCP / thinking / memory through one place. Also seeds
        # _pipeline["llm_lock"] when --think is on, but only if it's not
        # already set by the cron runner above.
        prev_lock = _pipeline.get("llm_lock")
        init_extensions(args, client)
        if prev_lock is not None:
            _pipeline["llm_lock"] = prev_lock

        try:
            if prompt:
                run_command(client, prompt)
                return 0
            return cli_loop(client)
        finally:
            if cron_runner is not None:
                cron_runner.shutdown(wait=False)
            shutdown_extensions(wait=False)
    finally:
        lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
