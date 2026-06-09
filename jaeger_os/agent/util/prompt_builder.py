"""System-prompt assembly.

A thin Phase-1 surface — the actual layered prompt construction (identity,
JAEGER_OS_CONTEXT, mandatory rules, operating discipline, skill index,
runtime tail, etc.) lives in ``jaeger_os.agent.prompts.prompts.build_system_prompt``
today and will move here as part of Phase 5/6 once the loop is the new
agent's job. For Phase 1, all we need is the entry point the agent will
call. The full layered build is one function call away; we don't
re-implement it yet.

Adapter-specific rendering — Anthropic tools as an API parameter,
OpenAI tools list, Hermes-XML inline ``<tools>`` block — happens at the
adapter layer, not here.
"""

from __future__ import annotations

from typing import Any


def build_system_prompt(layout: Any = None, *, base: str | None = None) -> str:
    """Return the assembled system prompt for the current instance.

    Phase-1 behaviour: defers to ``jaeger_os.agent.prompts.prompts.build_system_prompt``
    when a ``layout`` is provided (so existing instances keep working
    unchanged through Phases 2-4), or returns ``base`` directly when
    given (the path tests use to provide a known prompt without booting
    an instance).
    """
    if base is not None:
        return base
    if layout is None:
        return ""
    try:
        from jaeger_os.agent.prompts.prompts import build_system_prompt as _legacy_build
        return _legacy_build(layout)
    except Exception:  # noqa: BLE001 — prompt assembly must never crash boot
        return ""


__all__ = ["build_system_prompt"]
