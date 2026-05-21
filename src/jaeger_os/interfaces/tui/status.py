"""Status panel + status bar renderers for the Jaeger-OS TUI.

Hermes-agent-style: a "boot panel" right after the banner showing
version, tools-by-category, skills, session info; and a one-line
status bar at the bottom of the screen with live counters.

Renderers return Rich `RenderableType` so the caller (``app.py``)
controls layout + when to redraw. Parallel implementation to
:mod:`lilith.interfaces.tui.status` — same hermes-agent shape,
jaeger's wider tool surface.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from rich.box import ROUNDED
from rich.console import Group
from rich.panel import Panel
from rich.text import Text


# ── Tool catalog (grouped) ──────────────────────────────────────────


# Tool name → display category (mirrors hermes-agent's tool grouping).
# 54 builtin tools across 22 categories; the catalog below reflects
# what's registered by :func:`jaeger_os.main._register_builtins`.
TOOL_GROUPS: dict[str, list[str]] = {
    "time":         ["get_time"],
    "math":         ["calculate"],
    "host":         ["system_status"],
    "file":         ["write_file", "append_file", "patch", "delete_file",
                     "read_file", "list_skill_dir", "search_files"],
    "memory":       ["remember", "recall", "forget",
                     "list_facts", "search_memory"],
    "scheduling":   ["schedule_prompt", "list_schedules",
                     "cancel_schedule"],
    "web":          ["web_search", "web_extract", "get_weather"],
    "code":         ["run_python", "run_in_venv", "terminal"],
    "packages":     ["install_package", "list_venv_packages"],
    "models":       ["list_models", "download_model"],
    "marketplace":  ["package_skill", "benchmark_skill"],
    "background":   ["start_background", "list_background",
                     "check_background", "stop_background"],
    "deepthink":    ["propose_deep_think_task", "list_deep_think_queue"],
    "board":        ["board_view", "board_add", "board_move",
                     "board_update"],
    "interaction":  ["clarify", "help_me"],
    "credentials":  ["get_credential", "list_credentials"],
    "speech":       ["text_to_speech"],
    "listen":       ["listen"],
    "vision":       ["vision_analyze", "image_generate"],
    "os":           ["open_on_host"],
    "agent":        ["delegate_task", "send_message", "reload_skills"],
    "plugins":      ["list_plugins", "setup_plugin"],
}


def _format_tool_group(name: str, tools: list[str]) -> Text:
    line = Text()
    line.append(f"{name}: ", style="bold cyan")
    line.append(", ".join(tools), style="dim")
    return line


# ── Boot status panel ──────────────────────────────────────────────


def boot_panel(
    *,
    version: str,
    instance_name: str,
    model_name: str,
    session_id: str,
    instance_dir: Path,
) -> Panel:
    """The fat status panel shown right after the banner. One pass at
    boot; the running TUI doesn't redraw it. Inspired by the
    hermes-agent screenshot (right column with version, tools by
    category, session info)."""
    header = Text()
    header.append(f"Jaeger-OS {version}", style="bold yellow")
    header.append(f"  ·  instance: {instance_name}", style="dim")
    header.append(f"  ·  model: {model_name}", style="dim")

    tools_block = Group(
        Text("▼ Available Tools", style="bold yellow"),
        *(_format_tool_group(name, tools) for name, tools in TOOL_GROUPS.items()),
    )

    session_block = Text()
    session_block.append("\n")
    session_block.append("Session: ", style="bold")
    session_block.append(session_id, style="dim")
    session_block.append("\n")
    session_block.append("Instance dir: ", style="bold")
    session_block.append(str(instance_dir), style="dim")

    body = Group(header, Text(""), tools_block, session_block)
    return Panel(
        body,
        box=ROUNDED,
        border_style="yellow",
        padding=(1, 2),
    )


# ── Status bar (footer) ────────────────────────────────────────────


def status_bar(
    *,
    model_name: str,
    state: str = "ready",
    elapsed_s: float = 0.0,
    context_tokens: int = 0,
    context_max: int = 8192,
    uptime_s: float = 0.0,
    voice_state: str = "off",
) -> Text:
    """Render the one-line status bar shown at the bottom of the
    screen. Updates between turns; the per-turn ruminating animation
    lives in :func:`thinking_indicator`."""
    bits: list[tuple[str, str]] = []

    # State + elapsed
    state_glyph = {
        "ready": "○",
        "thinking": "(¬_¬)",
        "tool": "▸",
        "speaking": "🔊",
        "error": "⚠",
    }.get(state, "•")
    state_text = f"{state_glyph} {state}"
    if elapsed_s > 0:
        state_text += f"  {elapsed_s:5.1f}s"
    bits.append((state_text, "yellow"))

    # Model
    bits.append((model_name, "dim cyan"))

    # Context usage
    pct = (context_tokens / context_max) * 100 if context_max else 0
    bar_width = 10
    filled = int(bar_width * (context_tokens / context_max)) if context_max else 0
    bar = "█" * filled + "░" * (bar_width - filled)
    ctx = f"{context_tokens:,}/{context_max:,}  [{bar}] {pct:3.0f}%"
    bits.append((ctx, "dim green"))

    # Uptime
    hours = int(uptime_s // 3600)
    minutes = int((uptime_s % 3600) // 60)
    bits.append((f"up {hours}h {minutes:02d}m", "dim"))

    # Mic / always-listening voice loop. Labelled "mic" so it isn't
    # mistaken for TTS — text_to_speech works regardless of this state;
    # this tracks the hands-free STT loop (python -m jaeger_os --voice).
    bits.append((f"mic {voice_state}", "dim"))

    out = Text()
    for i, (s, style) in enumerate(bits):
        if i > 0:
            out.append("  │  ", style="dim")
        out.append(s, style=style)
    return out


# ── Thinking / activity inline ─────────────────────────────────────


def thinking_panel(text: str, *, tokens: int | None = None) -> Panel:
    """A collapsible-looking 'Thinking' block shown inline before the
    final answer. Real collapsibility would need Textual; for v1 we
    just render it dimmer so the reader's eye skips it unless they
    care."""
    header = "▼ Thinking"
    if tokens is not None:
        header += f"  ~{tokens} tokens"
    return Panel(
        Text(text.strip(), style="dim italic"),
        title=header,
        title_align="left",
        border_style="dim",
        box=ROUNDED,
        padding=(0, 2),
    )


def tool_activity(tool_name: str, summary: str, elapsed_s: float) -> Text:
    """One-line tool-call activity, hermes-agent-style (▸ tool_name … elapsed)."""
    line = Text()
    line.append("▸ ", style="bold yellow")
    line.append(tool_name, style="bold cyan")
    if summary:
        line.append(f"  {summary}", style="dim")
    line.append(f"  ({elapsed_s:.2f}s)", style="dim yellow")
    return line


# ── Helpers ────────────────────────────────────────────────────────


def make_session_id() -> str:
    """Short stable session ID for the status panel."""
    return uuid.uuid4().hex[:8]


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
