"""Toolset scoping — the agent sees a small CORE set every turn; the
rest are grouped into named toolsets it loads on demand.

Two kinds of toolset:

  • **built-in classes** — the ~55 primitive tools grouped here by hand
    (``files``, ``code``, ``media``, …). They are not skills, just the
    raw surface, classified.
  • **skill toolsets** — registered at runtime by the skill loader. A
    skill IS a toolset: an experienced bundle of tools (+ the process
    to use them, which lives in the skill itself). The loader captures
    exactly which tools a skill registers and names that set after the
    skill — so a new skill becomes a loadable toolset with no edit here.

Why scope at all: routing accuracy on a local model degrades as the
visible tool count grows. The CORE set (~17 common tools) covers most
turns; ``load_toolset`` widens the view when a task needs more. The
active set only ever GROWS within a session, so the tool-schema KV
prefix is re-prefilled at most once per widening, never thrashed.

All tools stay REGISTERED on the agent regardless — this only controls
what appears in the schema the model sees. A tool in no toolset is
visible by default (fail-open): a new tool is never silently hidden.
"""

from __future__ import annotations

import os


def _scoping_enabled() -> bool:
    """Toolset scoping is OPT-IN. The timing benchmark showed the
    explicit ``load_toolset`` meta-step REGRESSED routing on Gemma 4
    (85% → 67%) — the model handles a 64-tool surface fine, but does
    not reliably realise it must load a toolset first. Default OFF:
    every tool is visible (the proven 85% behavior).
    ``JAEGER_TOOLSET_SCOPING=1`` turns scoping on (e.g. to A/B a future
    auto-load-on-intent variant that drops the meta-step)."""
    return os.environ.get("JAEGER_TOOLSET_SCOPING", "0").strip().lower() in (
        "1", "true", "yes", "on",
    )


# CORE — always visible. The common, high-frequency tools.
CORE: frozenset[str] = frozenset({
    "get_time", "calculate", "system_status",
    "remember", "recall", "forget", "list_facts", "search_memory",
    "set_name", "update_soul",
    "web_search", "web_extract", "get_weather",
    "read_file", "write_file",
    "help_me", "clarify",
    "todo", "load_toolset",
})


# ── Lean surface (hermes-style) ──────────────────────────────────────
# A local model routes far better over ~20 curated tools than ~60. This
# is the surface the model sees every turn; everything else stays
# REGISTERED (callable / importable) but off the model's view. The set
# mirrors hermes's default tools, consolidated (memory is one tool, not
# five). JAEGER_FULL_TOOLS=1 exposes the whole surface (debug/power use).
LEAN_CORE: frozenset[str] = frozenset({
    "execute_code", "terminal",
    "read_file", "write_file", "patch", "search_files", "list_skill_dir",
    "web_search", "web_extract",
    "memory",
    "todo", "clarify", "delegate_task", "kanban", "skill",
    "computer_use", "browser",
    "vision_analyze", "image_generate", "text_to_speech",
})


def _lean_surface() -> bool:
    """The model sees only LEAN_CORE by default — the hermes-sized
    surface. ``JAEGER_FULL_TOOLS=1`` turns it off (every tool visible)."""
    return os.environ.get("JAEGER_FULL_TOOLS", "0").strip().lower() not in (
        "1", "true", "yes", "on",
    )


def model_visible(name: str) -> bool:
    """Whether tool ``name`` is exposed to the model this turn.

    Lean surface on (default) ⇒ LEAN_CORE **plus every skill-registered
    tool** — a loaded skill is a deliberately-chosen curated bundle, so
    all of its tools show (the lean filter only trims the raw builtin
    surface). Lean off ⇒ every registered tool."""
    if not _lean_surface():
        return True
    if name in LEAN_CORE:
        return True
    if name in _MCP_TOOLS:
        return True
    for members in _SKILL_TOOLSETS.values():
        if name in members:
            return True
    return False

# Built-in tool classes — loaded on demand via load_toolset(name).
TOOLSETS: dict[str, frozenset[str]] = {
    "files": frozenset({
        "append_file", "delete_file", "patch", "search_files",
        "list_skill_dir",
    }),
    "code": frozenset({
        "run_python", "run_in_venv", "terminal", "install_package",
        "list_venv_packages",
    }),
    "media": frozenset({
        "text_to_speech", "listen", "vision_analyze", "image_generate",
    }),
    "scheduling": frozenset({
        "schedule_prompt", "list_schedules", "cancel_schedule",
    }),
    "background": frozenset({
        "start_background", "list_background", "check_background",
        "stop_background", "open_on_host",
    }),
    "skills": frozenset({
        "reload_skills", "package_skill", "benchmark_skill",
        "propose_deep_think_task", "list_deep_think_queue",
    }),
    "board": frozenset({
        "board_view", "board_add", "board_move", "board_update",
    }),
    "credentials": frozenset({"get_credential", "list_credentials"}),
    "plugins": frozenset({"list_plugins", "setup_plugin", "send_message"}),
    "models": frozenset({"list_models", "download_model", "model_location"}),
    "delegation": frozenset({"delegate_task"}),
}

# One-line description per built-in class — for the load_toolset catalog.
TOOLSET_SUMMARY: dict[str, str] = {
    "files": "append, delete, patch, search files; list the workspace",
    "code": "run Python, shell/terminal, install packages, venv exec",
    "media": "text-to-speech, mic capture, vision, image generation",
    "scheduling": "schedule, list, cancel cron prompts",
    "background": "long-running background processes; open URLs/apps",
    "skills": "reload, package, benchmark skills; deep-think queue",
    "board": "the kanban task board",
    "credentials": "list and read stored credentials",
    "plugins": "list, set up plugins; send messages",
    "models": "list and download models",
    "delegation": "hand subtasks to sub-agents",
}

# Skill toolsets — populated at runtime by the skill loader. A skill is
# its own toolset; the loader records exactly what tools it registered.
_SKILL_TOOLSETS: dict[str, frozenset[str]] = {}
_SKILL_SUMMARY: dict[str, str] = {}

# MCP tools — re-exported from configured MCP servers at startup. Like a
# skill, a configured MCP server is deliberately loaded, so its tools
# are never lean-filtered out of the model's view.
_MCP_TOOLS: set[str] = set()


def register_mcp_tools(names: list[str]) -> None:
    """Record MCP tool names so the lean surface keeps them visible."""
    _MCP_TOOLS.update(n for n in (names or []) if n)

# Active extended toolsets for the session. Core is always implicitly on.
_active: set[str] = set()


def register_skill_toolset(name: str, tools: list[str],
                           summary: str = "") -> None:
    """Register a skill's tools as a named toolset. Called by the skill
    loader once per skill — the skill itself defines the membership."""
    name = (name or "").strip().lower()
    if not name or not tools:
        return
    _SKILL_TOOLSETS[name] = frozenset(tools)
    _SKILL_SUMMARY[name] = summary or f"the {name} skill"


def reset_toolsets() -> None:
    """Reset to core-only. Called at session start / instance switch."""
    _active.clear()


def enable_toolset(name: str) -> bool:
    """Make a toolset (built-in class or skill) visible. False if unknown."""
    name = (name or "").strip().lower()
    if name in TOOLSETS or name in _SKILL_TOOLSETS:
        _active.add(name)
        return True
    return False


def active_toolset_names() -> set[str]:
    """The toolsets currently visible (``core`` always included)."""
    return {"core"} | _active


def all_toolsets() -> dict[str, str]:
    """Every loadable toolset → its one-line summary (built-ins + skills)."""
    return {**TOOLSET_SUMMARY, **_SKILL_SUMMARY}


def _members(toolset: str) -> frozenset[str]:
    return TOOLSETS.get(toolset) or _SKILL_TOOLSETS.get(toolset) or frozenset()


def tool_visible(name: str) -> bool:
    """Whether tool ``name`` is currently exposed to the model. With
    scoping OFF (the default), every tool is visible."""
    if not _scoping_enabled():
        return True
    if name in CORE:
        return True
    for ts in _active:
        if name in _members(ts):
            return True
    # Fail-open: a tool that belongs to NO toolset is never hidden.
    in_any = (any(name in m for m in TOOLSETS.values())
              or any(name in m for m in _SKILL_TOOLSETS.values()))
    return not in_any
