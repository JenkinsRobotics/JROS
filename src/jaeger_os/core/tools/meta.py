"""Meta-tools — the model's introspection surface for its own toolbox.

JROS ships with a lean tool surface by default (``JAEGER_TOOLSET_SCOPING=1``
is on; the model sees CORE + a catalog, not all ~70 schemas). Two
meta-tools make that workable:

  - :func:`describe_tool` — return the schema of any registered tool,
    even one currently hidden from the model. Cheap peek; doesn't
    change the active set.
  - :func:`load_toolset` lives in ``main.py`` for legacy reasons; it
    widens the active set so a whole category becomes visible. We
    keep that wiring untouched and only add ``describe_tool`` here.

Why a separate ``meta.py`` instead of folding into ``_common.py``:
the meta-tools touch the agent's tool *registry* rather than the
filesystem or the model — distinct enough that growing this file
(future: ``introspect_message_count``, ``trace_last_turn``) makes
sense in one place.
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


__all__ = ["describe_tool"]
