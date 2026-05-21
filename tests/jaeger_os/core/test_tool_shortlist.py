from __future__ import annotations

from jaeger_os.core.llm_model import _shortlist_tools_for_turn


def _tool(name: str, description: str = "") -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {"type": "object", "properties": {}},
        },
    }


def _many_tools(names: list[str], filler: int = 50) -> list[dict]:
    tools = [_tool(name) for name in names]
    tools.extend(_tool(f"unused_{idx}") for idx in range(filler))
    return tools


def _messages(text: str) -> list[dict]:
    return [{"role": "user", "content": text}]


def test_shortlist_keeps_multi_step_file_tools() -> None:
    tools = _many_tools([
        "clarify", "help_me", "todo", "load_toolset",
        "read_file", "write_file", "append_file", "patch",
        "run_python", "text_to_speech", "web_search",
    ])

    selected = _shortlist_tools_for_turn(
        tools,
        _messages("Create notes.txt, append a closing line, then read it out loud."),
        limit=14,
    )
    names = {tool["function"]["name"] for tool in selected}

    assert "write_file" in names
    assert "append_file" in names
    assert "read_file" in names
    assert "text_to_speech" in names
    assert len(selected) <= 14


def test_shortlist_keeps_computer_use_tools_for_mac_task() -> None:
    tools = _many_tools([
        "clarify", "help_me", "todo", "load_toolset",
        "computer_do", "computer_use", "computer_capture",
        "computer_look", "computer_windows", "computer_open", "computer_click",
        "read_file", "write_file", "patch",
    ])

    selected = _shortlist_tools_for_turn(
        tools,
        _messages("Use the computer to open Safari, click the Downloads window, and scroll down."),
        limit=16,
    )
    names = {tool["function"]["name"] for tool in selected}

    assert "computer_do" in names
    assert "computer_use" in names
    assert "computer_capture" in names
    assert "computer_windows" in names
    assert len(selected) <= 16


def test_shortlist_is_conservative_for_ambiguous_prompt() -> None:
    tools = _many_tools([
        "clarify", "help_me", "todo", "load_toolset",
        "read_file", "write_file", "patch",
    ])

    selected = _shortlist_tools_for_turn(
        tools,
        _messages("Can you handle this for me?"),
        limit=12,
    )

    assert selected == tools


def test_shortlist_can_be_disabled(monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_AUTO_TOOL_SHORTLIST", "0")
    tools = _many_tools(["calculate", "get_time"])

    selected = _shortlist_tools_for_turn(
        tools,
        _messages("Calculate 12 plus 30."),
        limit=8,
    )

    assert selected == tools
