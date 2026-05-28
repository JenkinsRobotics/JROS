"""gpt-oss harmony dialect.

gpt-oss was trained on OpenAI's *harmony* response format, where tool
calls travel on a dedicated ``<|channel|>commentary`` channel. A full
harmony renderer is a follow-up; for now the presentation prose asks the
model to emit a ChatML-style ``<tool_call>…</tool_call>`` (which the
drift parser already reads back), so at least the tools surface instead
of the model answering as a plain chatbot.

Parsing therefore reuses the ChatML JSON-envelope extractor.
"""

from __future__ import annotations

from typing import Any

from . import _shared, chatml


def extract_calls(text: str) -> list[dict[str, Any]]:
    """Until a native harmony-channel parser lands, gpt-oss is steered
    to the ChatML ``<tool_call>`` envelope — so reuse that extractor."""
    return chatml.extract_envelope(text)


def render_tools(tools: list[Any]) -> str:
    """Present ``tools`` to gpt-oss. Minimal ChatML-style fallback (a
    full harmony-channel renderer is a follow-up)."""
    if not tools:
        return ""
    schema_json = _shared.tool_schemas_json(tools)
    return (
        "You have tools available. To call one, emit:\n"
        "<tool_call>\n{\"name\": <tool-name>, \"arguments\": <json>}\n"
        "</tool_call>\n"
        f"<tools>\n{schema_json}\n</tools>"
    )


def render_tool_call(name: str, args: dict[str, Any]) -> str:
    """Echo a prior call in the same ChatML-style form gpt-oss is
    steered to emit."""
    return chatml.render_tool_call(name, args)


def render_tool_result(content: str) -> str:
    return chatml.render_tool_result(content)


__all__ = [
    "extract_calls", "render_tools", "render_tool_call", "render_tool_result",
]
