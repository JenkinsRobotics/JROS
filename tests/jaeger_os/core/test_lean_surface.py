"""Lean tool surface + the consolidated memory tool.

The model sees a hermes-sized core (~20 tools), not all ~60 — routing
on a local model degrades as the surface grows. And memory is ONE
action-dispatch tool instead of five (remember/recall/forget/list/search).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from jaeger_os.core import tools
from jaeger_os.core.toolsets import LEAN_CORE, model_visible


# ── lean surface ─────────────────────────────────────────────────────


def test_core_tools_are_visible_to_the_model() -> None:
    for name in ("execute_code", "memory", "read_file", "write_file",
                 "web_search", "todo", "computer_use"):
        assert model_visible(name), name


def test_archived_tools_are_hidden_from_the_model() -> None:
    # Still registered + callable — just off the model's view.
    for name in ("get_time", "calculate", "board_add", "schedule_prompt",
                 "remember", "run_python", "install_package"):
        assert not model_visible(name), name


def test_full_tools_env_exposes_everything(monkeypatch) -> None:
    monkeypatch.setenv("JAEGER_FULL_TOOLS", "1")
    assert model_visible("get_time") is True
    assert model_visible("anything_at_all") is True


def test_lean_core_is_hermes_sized() -> None:
    assert 12 <= len(LEAN_CORE) <= 26  # ~20, not ~60 — the whole point


def test_mcp_tools_are_not_lean_filtered() -> None:
    # A configured MCP server is deliberately loaded — the lean surface
    # must not hide the tools it re-exports.
    from jaeger_os.core.toolsets import register_mcp_tools
    assert model_visible("weather-server:get_forecast") is False
    register_mcp_tools(["weather-server:get_forecast"])
    assert model_visible("weather-server:get_forecast") is True


# ── consolidated memory tool ─────────────────────────────────────────


@pytest.fixture()
def bound(tmp_path):
    from jaeger_os.core import memory as mem
    mem.bind(SimpleNamespace(memory_dir=tmp_path / "memory"))
    yield


def test_memory_remember_then_recall(bound) -> None:
    r = tools.memory(action="remember", key="hometown", value="Seattle",
                     category="contacts")
    assert r["ok"] is True
    got = tools.memory(action="recall", key="hometown")
    assert got["ok"] is True and got["value"] == "Seattle"


def test_memory_forget(bound) -> None:
    tools.memory(action="remember", key="x", value="1")
    assert tools.memory(action="forget", key="x")["ok"] is True
    assert tools.memory(action="recall", key="x")["found"] is False


def test_memory_list_groups_by_category(bound) -> None:
    tools.memory(action="remember", key="sara", value="555",
                 category="contacts")
    r = tools.memory(action="list")
    assert r["ok"] is True
    assert "contacts" in r["by_category"]


def test_memory_search_action_runs(bound) -> None:
    r = tools.memory(action="search", query="anything")
    assert r["ok"] is True  # found may be 0; the action must not error


def test_memory_rejects_unknown_action(bound) -> None:
    r = tools.memory(action="teleport")
    assert r["ok"] is False and "unknown" in r["error"]


def test_memory_remember_needs_key_and_value(bound) -> None:
    assert tools.memory(action="remember", key="only_key")["ok"] is False
