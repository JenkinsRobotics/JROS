"""Meta-tools — the model's introspection surface for its own toolbox.

When the lean tool surface is on (opt-in via ``JAEGER_TOOLSET_SCOPING=1``;
default OFF in 0.1.0), the model sees a CORE set + a catalog of every
other toolset. Two meta-tools make that pattern workable:

  - :func:`describe_tool` — peek at any registered tool's schema
    without changing the active set. Cheap.
  - :func:`load_toolset` — widen the active set to include a whole
    category for the rest of the session.

Both also exist when the lean surface is OFF — describe_tool stays
useful as introspection, load_toolset is a no-op-by-config but won't
break.

Why a separate ``meta.py`` instead of folding into ``_common.py``:
the meta-tools touch the agent's tool *registry* rather than the
filesystem or the model — distinct enough that growing this file
(future: ``introspect_message_count``, ``trace_last_turn``) makes
sense in one place.

Both tools are registered at module-import time via
``register_tool_from_function`` so they're available before any
agent is built — main.py used to wrap them again inside the agent
construction closure, which created a drift risk (two copies of the
same docstring + dispatch shape).
"""

from __future__ import annotations

from typing import Any

from jaeger_os.agent.schemas.tool_registry import register_tool_from_function


@register_tool_from_function
def describe_tool(name: str) -> dict[str, Any]:
    """Show the FULL schema (description + parameter shape) of a single
    tool — even one that's not currently in the agent's visible
    toolset. Use this when you see a tool name in the catalog and want
    to know exactly what arguments it takes BEFORE deciding to use it
    (or before calling ``load_toolset`` to bring its whole category in).

    Cheaper than ``load_toolset`` when only one specific tool is
    needed: the catalog tells the model what exists, ``describe_tool``
    shows how to call it.

    Returns ``{ok, name, description, parameters}`` on success or
    ``{ok: False, error}`` for an unknown name.
    """
    from jaeger_os.agent.schemas.tool_registry import get_tool, has_tool

    clean = (name or "").strip()
    if not clean:
        return {"ok": False, "error": "empty tool name"}
    if not has_tool(clean):
        return {"ok": False, "error": f"unknown tool {name!r}"}
    tool = get_tool(clean)
    schema: dict[str, Any] = (
        tool.to_openai_schema() if hasattr(tool, "to_openai_schema") else {}
    )
    function = schema.get("function", {}) if isinstance(schema, dict) else {}
    return {
        "ok": True,
        "name": function.get("name") or tool.name,
        "description": function.get("description", ""),
        "parameters": function.get("parameters", {}),
    }


@register_tool_from_function
def load_toolset(name: str = "") -> dict[str, Any]:
    """Make a group of extra tools visible. You start each turn with
    a small CORE toolset; everything else is grouped — built-in
    classes (``files``, ``code``, ``media``, …) and skills (each skill
    is its own toolset of curated tools).

    Call this the MOMENT a task needs a capability you don't see a
    tool for — BEFORE concluding you can't do it. The new tools appear
    on your very next step. Call with no name (or an unknown one) to
    get the catalog of every toolset and what it holds. Returns the
    toolsets now active.

    No-op when ``JAEGER_TOOLSET_SCOPING`` is off (the 0.1.0 default) —
    every tool is already visible. The active-set tracking still works
    so this is harmless to call regardless of the scoping mode.
    """
    from jaeger_os.core.skills.toolsets import (
        active_toolset_names, all_toolsets, enable_toolset,
    )
    clean = (name or "").strip().lower()
    if enable_toolset(clean):
        return {"ok": True, "loaded": clean,
                "active": sorted(active_toolset_names())}
    return {
        "ok": False,
        "error": (f"unknown toolset {name!r}" if clean
                  else "give a toolset name — catalog below"),
        "available": all_toolsets(),
    }


__all__ = ["describe_tool", "load_toolset"]
