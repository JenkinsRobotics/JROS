"""Toolset scoping — the model sees a small CORE set and loads the rest
on demand, so it never routes over all ~60 tools at once. A skill is its
own self-describing toolset.
"""

from __future__ import annotations

import pytest

from jaeger_os.core.skills import toolsets as ts


@pytest.fixture(autouse=True)
def _clean_toolset_state(monkeypatch):
    """Toolset state is module-global — isolate each test. These tests
    exercise the scoping LOGIC, so enable it (it is opt-in by default)."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    ts.reset_toolsets()
    ts._SKILL_TOOLSETS.clear()
    ts._SKILL_SUMMARY.clear()
    yield
    ts.reset_toolsets()
    ts._SKILL_TOOLSETS.clear()
    ts._SKILL_SUMMARY.clear()


def test_scoping_off_by_default_shows_everything(monkeypatch) -> None:
    """With scoping disabled (the default — reverted after Gemma 4
    routing regressed from 100% to 67.6% under naive scoping), every
    tool is visible. Opt into the lean surface via
    ``JAEGER_TOOLSET_SCOPING=1`` when context is tight."""
    monkeypatch.delenv("JAEGER_TOOLSET_SCOPING", raising=False)
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    ts.reset_toolsets()
    assert ts.tool_visible("get_time")
    assert ts.tool_visible("run_python")       # would be hidden if scoped
    assert ts.tool_visible("schedule_prompt")
    assert ts.tool_visible("anything_at_all")


def test_scoping_on_via_env_hides_categorised_tools(monkeypatch) -> None:
    """``JAEGER_TOOLSET_SCOPING=1`` enables the lean surface — useful
    for context-tight runs, accepts the routing regression on some
    models in exchange for prompt-prefix savings."""
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    monkeypatch.delenv("JAEGER_FULL_TOOLS", raising=False)
    ts.reset_toolsets()
    assert ts.tool_visible("get_time")        # CORE
    assert not ts.tool_visible("run_python")  # in the ``code`` toolset → hidden
    assert ts.tool_visible("anything_at_all")  # fail-open for unclassified


def test_full_tools_env_overrides_explicit_scoping(monkeypatch) -> None:
    """``JAEGER_FULL_TOOLS=1`` wins even when scoping is asked for —
    a kill-switch for bench harnesses + debug."""
    monkeypatch.setenv("JAEGER_FULL_TOOLS", "1")
    monkeypatch.setenv("JAEGER_TOOLSET_SCOPING", "1")
    assert ts.tool_visible("run_python")
    assert ts.tool_visible("schedule_prompt")


# ── core + built-in classes ─────────────────────────────────────────


def test_core_tools_always_visible() -> None:
    for name in ("get_time", "remember", "web_search", "todo", "load_toolset"):
        assert ts.tool_visible(name), name


def test_non_core_tool_hidden_until_its_toolset_loads() -> None:
    assert not ts.tool_visible("run_python")     # in 'code'
    assert ts.enable_toolset("code") is True
    assert ts.tool_visible("run_python")


def test_loading_one_toolset_does_not_reveal_another() -> None:
    ts.enable_toolset("code")
    assert ts.tool_visible("run_python")          # code — loaded
    assert not ts.tool_visible("schedule_prompt")  # scheduling — not loaded


def test_unknown_toolset_is_rejected() -> None:
    assert ts.enable_toolset("nonexistent") is False


def test_uncategorised_tool_fails_open() -> None:
    """A tool in no toolset at all is never silently hidden."""
    assert ts.tool_visible("a_brand_new_uncategorised_tool")


def test_reset_returns_to_core_only() -> None:
    ts.enable_toolset("code")
    ts.reset_toolsets()
    assert not ts.tool_visible("run_python")


def test_active_toolset_names_always_includes_core() -> None:
    assert "core" in ts.active_toolset_names()
    ts.enable_toolset("code")
    assert ts.active_toolset_names() == {"core", "code"}


# ── skills as self-describing toolsets ──────────────────────────────


def test_skill_registers_as_its_own_toolset() -> None:
    ts.register_skill_toolset("computer", ["computer_do", "computer_click"],
                              summary="drive macOS apps")
    assert not ts.tool_visible("computer_do")     # skill toolset not loaded
    assert ts.enable_toolset("computer") is True
    assert ts.tool_visible("computer_do")
    assert ts.tool_visible("computer_click")


def test_catalog_lists_built_ins_and_skills() -> None:
    ts.register_skill_toolset("computer", ["computer_do"],
                              summary="drive macOS apps")
    cat = ts.all_toolsets()
    assert "code" in cat and "files" in cat        # built-in classes
    assert cat["computer"] == "drive macOS apps"   # skill toolset
