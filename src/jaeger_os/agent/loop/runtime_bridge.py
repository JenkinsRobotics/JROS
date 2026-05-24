"""Phase-6 migration runtime bridge.

Builds a :class:`JaegerAgent` from an existing JROS client and drives
one turn through it. Designed to drop in alongside the legacy
``_run_via_iter`` path so the benchmark can A/B both — same client,
same model, same tools, different loop.

This file is **migration-only**. When pydantic-ai is gone the bridge
collapses into ``main.py`` directly and this module is deleted.

The bridge owns these decisions:

  • adapter selection from a JROS client (``LocalLlamaAdapter`` for the
    in-process ``LlamaCppPythonClient`` shape; ``AnthropicAdapter`` /
    ``OpenAIAdapter`` for ``ExternalModelClient``)
  • per-session ``JaegerAgent`` caching — one agent per session key so
    history accumulates across turns
  • the skip-final finalizer that calls back into ``client.chat`` for
    the bounded paraphrasing pass (same shape as the legacy
    ``_fast_finalize_sync``)
  • the latency-row payload shape returned to the caller, so
    ``run_command`` writes the same JSONL schema the benchmark reads.

It does **not** own the print formatting, the latency-report dataclass
construction, the episodic-memory write, or session-history clamping —
those stay in ``main.py`` so legacy and new paths share one set of
side effects.
"""

from __future__ import annotations

import os
import time
from typing import Any

from jaeger_os.agent.adapters.anthropic import AnthropicAdapter
from jaeger_os.agent.adapters.base import ProviderAdapter
from jaeger_os.agent.adapters.local_llama import LocalLlamaAdapter
from jaeger_os.agent.adapters.openai import OpenAIAdapter
from jaeger_os.agent.loop.callbacks import AgentCallbacks
from jaeger_os.agent.loop.jaeger_agent import JaegerAgent
from jaeger_os.agent.schemas.message_types import Message


def _adapter_for_client(
    client: Any,
    *,
    system_prompt: str = "",
) -> ProviderAdapter:
    """Map a JROS client object onto the adapter that owns its wire
    format. Three branches today; one per concrete client class.

    The detection is **duck-typed** rather than class-checked so we
    don't drag in optional dependencies just to ``isinstance`` against
    them. ``client.llm`` is the in-process llama-cpp ``Llama``;
    ``client.ext`` is the dataclass on the external client.
    """
    # In-process llama-cpp: there's no HTTP, no API key, the model is
    # already loaded and warmed.
    llm = getattr(client, "llm", None)
    if llm is not None:
        return LocalLlamaAdapter(
            model=getattr(client, "model_name", "local"),
            llama=llm,
        )

    ext = getattr(client, "ext", None)
    if ext is not None:
        provider = getattr(ext, "provider", "openai")
        model = getattr(ext, "model", "")
        api_key = getattr(client, "_api_key", "") or ""
        timeout_s = float(getattr(ext, "timeout_s", 60.0) or 60.0)
        if provider == "anthropic":
            return AnthropicAdapter(
                api_key=api_key,
                model=model,
                timeout_s=timeout_s,
            )
        # Everything else (openai, gemini, ollama, ollama-cloud,
        # lmstudio) rides the OpenAI-compat surface.
        return OpenAIAdapter(
            provider=provider,
            model=model,
            api_key=api_key,
            base_url=getattr(ext, "base_url", None),
            timeout_s=timeout_s,
        )

    # Unknown client shape — caller should have caught this; raise here
    # rather than silently building the wrong adapter.
    raise RuntimeError(
        f"runtime_bridge cannot select an adapter for client "
        f"{type(client).__name__}; expected ``.llm`` or ``.ext``."
    )


def _make_fast_finalize_finalizer(client: Any) -> Any:
    """Wrap the legacy ``_fast_finalize_sync`` so it satisfies the
    :data:`SkipFinalFinalizer` callable signature.

    Looked up **lazily on every call** rather than captured at build
    time — keeps the bridge compatible with ``main.py`` hot-reload (the
    test suite monkey-patches the legacy formatter to exercise error
    paths) and avoids an import-cycle if ``main.py`` is mid-import when
    the bridge is first reached.
    """
    def _finalize(tool_name: str, tool_result: Any, user_message: str) -> str:
        # ``tool_result`` from the agent loop is a stringified JSON
        # blob; decode if possible so the legacy formatter sees the
        # original dict it expects.
        decoded: Any = tool_result
        if isinstance(tool_result, str):
            try:
                import json
                decoded = json.loads(tool_result)
            except (TypeError, ValueError):
                decoded = tool_result
        try:
            from jaeger_os.main import _fast_finalize_sync  # late-bind
            return _fast_finalize_sync(client, user_message, tool_name, decoded)
        except Exception as exc:  # noqa: BLE001 — finalizer must never crash a turn
            return f"[finalize fallback: {type(exc).__name__}] {decoded}"

    return _finalize


def build_jaeger_agent(
    client: Any,
    *,
    system_prompt: str = "",
    toolsets: set[str] | frozenset[str] | list[str] | None = None,
    skip_final_tools: set[str] | frozenset[str] | None = None,
    callbacks: AgentCallbacks | None = None,
    max_iterations: int = 24,
) -> JaegerAgent:
    """Construct a :class:`JaegerAgent` wired against the provided
    JROS client. The skip-final finalizer is the legacy bounded-chat
    paraphraser so phrasing stays identical to the pre-refactor path.

    ``max_iterations=24`` matches the legacy ``_MAX_TOOL_CALLS`` ceiling
    so the loop backstop trips at the same point and the benchmark
    measures the same boundary.

    ``toolsets`` (Phase 7): when provided, the agent's tool catalogue
    is filtered to just those Hermes-style groups. When ``None``
    (default) every registered tool is exposed — useful for the
    transition period but burns ~10K tokens of schema per turn.
    """
    adapter = _adapter_for_client(client, system_prompt=system_prompt)
    return JaegerAgent(
        adapter=adapter,
        system_prompt=system_prompt,
        toolsets=toolsets,
        skip_final_tools=frozenset(skip_final_tools or ()),
        skip_final_finalizer=_make_fast_finalize_finalizer(client),
        callbacks=callbacks or AgentCallbacks(),
        max_iterations=max_iterations,
    )


def _tool_activity_lines(messages: list[Message]) -> list[str]:
    """Render the same one-line-per-tool-call activity strings the
    legacy ``_walk_new_messages`` printed. Matches the ``▸ tool(args)``
    shape so the TUI / latency log stays unchanged across the
    migration."""
    lines: list[str] = []
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        for tc in (msg.get("tool_calls") or []):
            name = tc.get("name") or ""
            args = tc.get("arguments") or {}
            if isinstance(args, dict) and args:
                args_repr = ", ".join(
                    f"{k}={v!r}" for k, v in list(args.items())[:2]
                )
            else:
                args_repr = ""
            lines.append(f"  ▸ {name}({args_repr})")
    return lines


def _first_decision_from(messages: list[Message]) -> dict[str, Any] | None:
    """Pluck the (tool, args) of the first tool call this turn. Used by
    the latency log to record the model's first routing decision —
    mirrors the legacy ``first_decision`` field byte-for-byte so the
    benchmark's per-prompt analysis still keys off the same field."""
    for msg in messages:
        if msg.get("role") != "assistant":
            continue
        tool_calls = msg.get("tool_calls") or []
        if tool_calls:
            tc = tool_calls[0]
            return {"tool": tc.get("name", ""), "args": tc.get("arguments") or {}}
    return None


def drive_one_turn(
    agent: JaegerAgent,
    user_text: str,
) -> dict[str, Any]:
    """Run one turn through the new agent and return a dict shaped like
    the legacy ``_run_with_fix_loop`` output (the bits the latency log
    cares about). The schema:

      • ``answer``         — final assistant text
      • ``tool_activity``  — ``["  ▸ tool(args)", …]``
      • ``first_decision`` — ``{"tool": name, "args": dict} | None``
      • ``elapsed_s``      — wall-clock for the turn
      • ``skipped``        — True when skip-final fired
      • ``halt_reason``    — None on clean finish; string on backstop hit
      • ``iterations``     — agent-loop iteration count
      • ``new_messages``   — the ``Message`` slice produced this turn
        (for history extension)
    """
    pre_len = len(agent.messages)
    started = time.perf_counter()
    answer = agent.run_turn(user_text)
    elapsed = time.perf_counter() - started

    new_messages = agent.messages[pre_len:]
    return {
        "answer": answer,
        "tool_activity": _tool_activity_lines(new_messages),
        "first_decision": _first_decision_from(new_messages),
        "elapsed_s": elapsed,
        "skipped": agent.last_skip_final,
        "halt_reason": agent.last_halt_reason,
        "iterations": agent.last_iteration_count,
        "new_messages": new_messages,
    }


def jaeger_agent_enabled() -> bool:
    """Single source of truth for the feature flag. Off by default —
    a stray env var won't accidentally flip production-routed runs onto
    the migration path.

    Set ``JAEGER_USE_NEW_AGENT=1`` to opt in; useful values
    (``1``, ``true``, ``yes``, ``on``) all flip it on, anything else
    keeps the legacy loop."""
    val = os.environ.get("JAEGER_USE_NEW_AGENT", "").strip().lower()
    return val in ("1", "true", "yes", "on")


__all__ = [
    "build_jaeger_agent",
    "drive_one_turn",
    "jaeger_agent_enabled",
]
