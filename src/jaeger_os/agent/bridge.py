"""Phase-6 migration bridge.

The legacy ``main.py`` registers every JROS tool against a pydantic-ai
``Agent`` via ``@agent.tool_plain``. Phase 6 needs the same tools
available to the new :class:`JaegerAgent` without duplicating the 48+
``@agent.tool_plain`` decorators. The bridge here introspects a
populated pydantic-ai agent and mirrors each tool into the
:mod:`jaeger_os.agent.tool_registry`, building a synthetic Pydantic
args model from the function signature.

This is **migration-only code**. When Phase 6 lands fully and
pydantic-ai is removed, the bridge goes too — built-in tools then
register directly via ``@register_tool``. Skill loading converts the
same way: ``register(jaeger_agent)`` instead of ``register(pai_agent)``.

The bridge is intentionally minimal in scope:

  • read tools out of the pydantic-ai agent
  • build a Pydantic args model from ``inspect.signature``
  • call ``register_tool_instance`` for each one

It does not touch the loop, the system prompt, or any callbacks —
those wire up at the ``JaegerAgent`` construction site.
"""

from __future__ import annotations

import inspect
from typing import Any, Callable, get_type_hints

from pydantic import BaseModel, ConfigDict, Field, create_model

from .tool_registry import register_tool_instance, unregister_tool
from .tool_schema import ToolDef


def _args_model_from_signature(
    fn: Callable[..., Any],
    *,
    name: str,
) -> type[BaseModel]:
    """Synthesize a Pydantic ``BaseModel`` from a function's signature.

    Uses ``get_type_hints`` rather than ``inspect.Parameter.annotation``
    so forward references (PEP 563 / ``from __future__ import annotations``)
    resolve to real types — JROS uses ``from __future__ import annotations``
    everywhere, so the raw annotations are strings until resolved.

    Optional parameters with defaults map to ``(type, default)``;
    required parameters map to ``(type, ...)`` (the Pydantic "required"
    sentinel). Untyped parameters fall back to ``Any``.
    """
    sig = inspect.signature(fn)
    try:
        hints = get_type_hints(fn)
    except Exception:  # noqa: BLE001 — forward refs that can't resolve get Any
        hints = {}

    fields: dict[str, Any] = {}
    for param in sig.parameters.values():
        if param.name in ("self", "cls"):
            continue
        # pydantic-ai's ``ctx`` param uses ``RunContext`` — skip; the
        # bridge handles plain tools only. ``tool_plain`` doesn't pass
        # ctx, but defensive.
        if param.kind in (
            inspect.Parameter.VAR_POSITIONAL,
            inspect.Parameter.VAR_KEYWORD,
        ):
            continue
        annotation = hints.get(param.name, Any)
        if param.default is inspect.Parameter.empty:
            fields[param.name] = (annotation, ...)
        else:
            fields[param.name] = (annotation, Field(default=param.default))

    # ``arbitrary_types_allowed`` because some JROS tools type-hint
    # callbacks or layout objects that Pydantic can't validate; let the
    # values through unchanged.
    return create_model(  # type: ignore[call-overload]
        f"{name.title().replace('_', '')}Args",
        __config__=ConfigDict(arbitrary_types_allowed=True),
        **fields,
    )


def _iter_pai_tools(pai_agent: Any) -> list[Any]:
    """Pull the ``Tool`` instances out of a pydantic-ai ``Agent``.

    The internal layout changed between pydantic-ai 0.x and 1.x:
    older builds put tools on ``agent._function_tools``; newer ones
    nest them under ``agent._function_toolset.tools``. Probe both so
    the bridge survives a dependency bump.
    """
    function_tools = getattr(pai_agent, "_function_tools", None)
    if function_tools:
        if isinstance(function_tools, dict):
            return list(function_tools.values())
        return list(function_tools)
    toolset = getattr(pai_agent, "_function_toolset", None)
    if toolset is not None:
        tools = getattr(toolset, "tools", None) or {}
        if isinstance(tools, dict):
            return list(tools.values())
        return list(tools)
    return []


def mirror_pydantic_ai_tools(pai_agent: Any) -> list[str]:
    """Walk every plain tool on ``pai_agent`` and register an equivalent
    :class:`ToolDef` in the agent-layer registry. Returns the list of
    names mirrored — useful for diagnostics + tests.

    Idempotent: re-running unregisters and re-registers each name, so a
    second ``build_agent`` call doesn't accumulate duplicate entries.
    """
    mirrored: list[str] = []
    for pai_tool in _iter_pai_tools(pai_agent):
        fn = getattr(pai_tool, "function", None)
        name = getattr(pai_tool, "name", None) or getattr(fn, "__name__", "")
        description = (
            getattr(pai_tool, "description", None)
            or inspect.getdoc(fn)
            or ""
        )
        if fn is None or not name:
            continue

        args_model = _args_model_from_signature(fn, name=name)
        tool_def = ToolDef(
            name=name,
            description=str(description),
            args_model=args_model,
            fn=fn,
        )
        # Idempotent: clear any stale registration before installing.
        # ``unregister_tool`` is a no-op when the name isn't registered,
        # so this is safe to call unconditionally on the first run too.
        unregister_tool(name)
        register_tool_instance(tool_def)
        mirrored.append(name)
    return mirrored


__all__ = ["mirror_pydantic_ai_tools"]
