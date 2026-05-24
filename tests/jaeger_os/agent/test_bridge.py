"""Phase-6 bridge — mirror pydantic-ai tools into the new registry.

Tests use a real ``pydantic_ai.Agent`` (no migration would survive a
mocked one) backed by ``TestModel`` so nothing reaches a real network.
"""

from __future__ import annotations

from typing import Optional

import pytest
from pydantic import ValidationError
from pydantic_ai import Agent
from pydantic_ai.models.test import TestModel

from jaeger_os.agent import (
    clear_registry,
    get_tool,
    get_tools,
    has_tool,
    mirror_pydantic_ai_tools,
)


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


def _build_pai_agent_with_demo_tools() -> Agent:
    """Stand-in for ``main.build_agent`` — a pydantic-ai agent with a
    couple of representative JROS-shaped tools wired on."""
    a: Agent = Agent(model=TestModel(), system_prompt="")

    @a.tool_plain
    def get_time(timezone: Optional[str] = None) -> dict:
        """The current date and time. Optional IANA timezone."""
        return {"now": "12:00", "tz": timezone or "UTC"}

    @a.tool_plain
    def calculate(expression: str) -> dict:
        """Evaluate an arithmetic expression."""
        return {"result": expression}

    @a.tool_plain
    def write_file(path: str, content: str) -> dict:
        """Write a file."""
        return {"ok": True, "path": path, "bytes": len(content)}

    return a


def test_mirror_returns_every_tool_name():
    a = _build_pai_agent_with_demo_tools()
    mirrored = mirror_pydantic_ai_tools(a)
    assert set(mirrored) == {"get_time", "calculate", "write_file"}


def test_mirrored_tools_are_in_the_registry():
    a = _build_pai_agent_with_demo_tools()
    mirror_pydantic_ai_tools(a)
    assert has_tool("get_time")
    assert has_tool("calculate")
    assert has_tool("write_file")
    assert {t.name for t in get_tools()} == {"get_time", "calculate", "write_file"}


def test_mirrored_tool_descriptions_carry_through():
    a = _build_pai_agent_with_demo_tools()
    mirror_pydantic_ai_tools(a)
    assert "current date and time" in get_tool("get_time").description
    assert "arithmetic" in get_tool("calculate").description


def test_mirrored_tool_dispatches_with_default_argument():
    """Optional args land in the synthesized model with their default —
    calling ``dispatch({})`` must use that default rather than raising."""
    a = _build_pai_agent_with_demo_tools()
    mirror_pydantic_ai_tools(a)
    result = get_tool("get_time").dispatch({})
    assert result == {"now": "12:00", "tz": "UTC"}


def test_mirrored_tool_dispatches_with_explicit_argument():
    a = _build_pai_agent_with_demo_tools()
    mirror_pydantic_ai_tools(a)
    result = get_tool("get_time").dispatch({"timezone": "Asia/Tokyo"})
    assert result == {"now": "12:00", "tz": "Asia/Tokyo"}


def test_mirrored_required_arg_validation_fires_on_missing():
    """Required args without defaults must reject ``{}`` via
    ``ValidationError`` — same contract the legacy pydantic-ai path
    gave the agent loop."""
    a = _build_pai_agent_with_demo_tools()
    mirror_pydantic_ai_tools(a)
    with pytest.raises(ValidationError):
        get_tool("calculate").dispatch({})


def test_mirror_is_idempotent():
    """Running the bridge twice should not duplicate registrations or
    raise."""
    a = _build_pai_agent_with_demo_tools()
    mirrored_1 = mirror_pydantic_ai_tools(a)
    mirrored_2 = mirror_pydantic_ai_tools(a)
    assert mirrored_1 == mirrored_2
    # Registry still has just one of each.
    assert len(get_tools()) == 3


def test_mirrored_tools_render_all_three_schemas():
    """The bridge produces synthetic args models, but the result is
    indistinguishable from a hand-written ``ToolDef`` — the three
    schema renderers must work the same."""
    import json

    a = _build_pai_agent_with_demo_tools()
    mirror_pydantic_ai_tools(a)
    tool = get_tool("write_file")
    anthropic = tool.to_anthropic_schema()
    openai = tool.to_openai_schema()
    hermes_block = json.loads(tool.to_hermes_xml_block())

    assert anthropic["name"] == "write_file"
    assert "path" in anthropic["input_schema"]["properties"]
    assert "content" in anthropic["input_schema"]["properties"]
    assert openai["function"]["name"] == "write_file"
    assert hermes_block["function"]["name"] == "write_file"


def test_mirror_handles_empty_pai_agent():
    """A fresh agent with no tools should mirror as an empty list, not
    raise."""
    a: Agent = Agent(model=TestModel(), system_prompt="")
    assert mirror_pydantic_ai_tools(a) == []
    assert get_tools() == []
