"""Slash-command parser for the Jaeger-OS TUI.

Hermes-agent style: lines starting with ``/`` are commands, not
prompts to the agent. The handler set covers admin operations the
agent loop shouldn't waste tokens on — model + instance management,
help, quit. Anything else routes to ``jaeger_os.main.run_command``.

Handlers receive (ctx, args_str). ``args_str`` is the remainder of
the line after the command name; handlers split it themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from rich.console import Console
from rich.table import Table
from rich.text import Text


@dataclass(frozen=True)
class SlashCommand:
    name: str                                                    # without leading slash
    summary: str
    handler: Callable[["SlashContext", str], "SlashResult"]


@dataclass
class SlashContext:
    """What a slash handler can poke at."""

    console: Console
    instance_dir: object  # pathlib.Path
    # The owning TUI instance — needed by handlers that want to mutate
    # session state (instance switch, model swap). None is allowed so
    # tests / banner-only flows don't have to construct a fake TUI.
    tui: Any = None
    facts: dict[str, str] | None = None
    extras: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SlashResult:
    """Return shape — ``quit=True`` ends the REPL; ``message`` is printed.

    ``extras`` is a side-channel for handlers that need to tell the REPL
    something specific (e.g. ``{"goal_just_set": True}`` so the REPL
    fires the first goal-loop turn immediately). ``frozen=True`` means
    we use a ``MappingProxyType``-wrapped default for safety."""

    quit: bool = False
    message: str = ""
    extras: dict[str, Any] = field(default_factory=dict)


# ── Handlers ─────────────────────────────────────────────────────────


def _help(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Render the help table inline."""
    table = Table(show_header=True, header_style="bold yellow")
    table.add_column("Command")
    table.add_column("What it does")
    for cmd in REGISTRY:
        table.add_row(f"/{cmd.name}", cmd.summary)
    ctx.console.print(table)
    return SlashResult()


def _quit(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    return SlashResult(quit=True, message="Bye.")


def _tools(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    from .status import TOOL_GROUPS, _format_tool_group
    for name, tools in TOOL_GROUPS.items():
        ctx.console.print(_format_tool_group(name, tools))
    return SlashResult()


def _facts(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """List stored facts from jaeger's memory layer."""
    from jaeger_os.core import memory as memory_mod
    try:
        rows = memory_mod.list_facts()
    except RuntimeError as exc:
        ctx.console.print(f"[yellow]facts unavailable: {exc}[/]")
        return SlashResult()
    if not rows:
        ctx.console.print("[dim]No facts saved yet.[/]")
        return SlashResult()
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Key")
    table.add_column("Value")
    for k, v in sorted(rows.items()):
        table.add_row(k, v[:120] + ("…" if len(v) > 120 else ""))
    ctx.console.print(table)
    return SlashResult()


def _reset(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    ctx.console.print(
        "[yellow]reset:[/] in-process session reset is a future feature. "
        "For now exit and restart for a fresh agent."
    )
    return SlashResult()


# ── Instance management ─────────────────────────────────────────────


def _instance(ctx: SlashContext, args: str) -> SlashResult:
    """``/instance`` — show active. ``/instance <name>`` — hot-switch."""
    target = args.strip()
    if not target:
        ctx.console.print(f"[bold]Active instance:[/] {ctx.instance_dir}")
        return SlashResult()
    if ctx.tui is None:
        ctx.console.print(
            "[yellow]Hot-switch unavailable in this TUI context.[/] "
            "Restart with `--instance " + target + "`."
        )
        return SlashResult()
    return _do_switch_instance(ctx, target)


def _instances(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """List every discoverable instance with its identity + status."""
    from jaeger_os.main import _list_instances
    from jaeger_os.core.schemas import Identity, load_yaml
    rows = _list_instances()
    if not rows:
        ctx.console.print("[dim]No instances found.[/]")
        return SlashResult()
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Identity")
    table.add_column("Voice")
    table.add_column("Path")
    current_path = str(ctx.instance_dir)
    for name, path, has_manifest in rows:
        marker = " *" if str(path) == current_path else ""
        if has_manifest:
            try:
                ident = load_yaml(path / "identity.yaml", Identity)
                ident_cell = f"{ident.name} — {ident.role[:50]}"
                voice = ident.voice_id or "(default)"
            except Exception as exc:  # noqa: BLE001
                ident_cell = f"(unreadable: {exc!s:.40})"
                voice = "—"
        else:
            ident_cell = "(no manifest — incomplete)"
            voice = "—"
        table.add_row(name + marker, ident_cell, voice, str(path))
    ctx.console.print(table)
    ctx.console.print(
        "[dim]Switch with [bold]/instance <name>[/]. "
        "`*` marks the active instance.[/]"
    )
    return SlashResult()


def _do_switch_instance(ctx: SlashContext, name: str) -> SlashResult:
    """Hot-switch the TUI to a different instance. Tears down the
    current llama-cpp client + lock, boots the new instance, swaps
    everything on the TUI in place. ~5-10s wall time (Gemma reload)."""
    tui = ctx.tui
    if tui is None:
        return SlashResult(message="No TUI context for switch.")
    try:
        with ctx.console.status(
            f"[bold yellow]switching to instance {name!r}…[/]",
            spinner="dots",
        ):
            tui.switch_instance(name)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Switch failed:[/] {exc}")
        return SlashResult()
    ctx.console.print(
        f"[green]Switched to {name!r}.[/] New instance dir: {tui.instance_dir}"
    )
    return SlashResult()


# ── Model management ────────────────────────────────────────────────


def _model(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """Show the active brain. Local llama-cpp by default; an external
    provider (LM Studio / OpenAI / Anthropic) when the instance config
    has `external_model.enabled: true`. Switching is config-driven —
    edit config.yaml and restart."""
    from jaeger_os.main import _pipeline
    cfg = _pipeline.get("config")
    if cfg is None:
        ctx.console.print(
            "[yellow]Model info unavailable[/] — no active pipeline yet."
        )
        return SlashResult()
    client = _pipeline.get("client")
    ext = getattr(cfg, "external_model", None)
    if ext is not None and ext.enabled and getattr(client, "kind", "local") == "external":
        ctx.console.print(f"[bold]Active brain:[/] external · {ext.provider}")
        ctx.console.print(f"[bold]Model:[/] {ext.model}")
        if ext.provider in ("lmstudio", "openai"):
            ctx.console.print(f"[bold]Endpoint:[/] {ext.base_url}")
        ctx.console.print("[dim]Local-first fallback: the bundled llama-cpp model.[/]")
    else:
        ctx.console.print(f"[bold]Active brain:[/] local · llama-cpp")
        ctx.console.print(f"[bold]Model:[/] {cfg.model.model_path}")
        if ext is not None and ext.enabled:
            ctx.console.print(
                "[yellow]Note:[/] external_model is enabled in config but "
                "the external endpoint was unreachable at boot — running local."
            )
        else:
            ctx.console.print(
                "[dim]To use an external model (LM Studio / Claude), set "
                "external_model in config.yaml — see docs/external_models.md.[/]"
            )
    return SlashResult()


def _models(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """List every model in the registry with cache status."""
    from jaeger_os.core.model_resolver import list_registered_models
    rows = list_registered_models()
    if not rows:
        ctx.console.print("[dim]No models registered.[/]")
        return SlashResult()
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Name")
    table.add_column("Size")
    table.add_column("Status")
    table.add_column("HF source")
    for m in rows:
        size = f"{m['size_gb']:.1f} GB" if m.get("size_gb") else "—"
        table.add_row(m["name"], size, m["status"], m["hf_repo"])
    ctx.console.print(table)
    ctx.console.print(
        "[dim]Download with [bold]/download <name>[/].[/]"
    )
    return SlashResult()


def _download(ctx: SlashContext, args: str) -> SlashResult:
    """Download a registered model into the user cache. No-op if the
    file is already cached."""
    name = args.strip()
    if not name:
        ctx.console.print(
            "[yellow]Usage:[/] /download <model-name>.  "
            "Run /models for the catalog."
        )
        return SlashResult()
    from jaeger_os.core.model_resolver import MODEL_REGISTRY, download_model
    if name not in MODEL_REGISTRY:
        ctx.console.print(
            f"[red]Unknown model {name!r}.[/] Known: "
            + ", ".join(sorted(MODEL_REGISTRY.keys()))
        )
        return SlashResult()
    try:
        with ctx.console.status(
            f"[bold yellow]downloading {name}…[/]", spinner="dots",
        ):
            path = download_model(name, progress=False)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Download failed:[/] {exc}")
        return SlashResult()
    ctx.console.print(f"[green]Downloaded:[/] {path}")
    return SlashResult()


# ── Plugin management (read-only — actually using a plugin still
#     goes through the corresponding agent tool / CLI) ──────────────


def _plugins(ctx: SlashContext, args: str) -> SlashResult:  # noqa: ARG001
    """List bundled plugins (discord, telegram, whisper_stt, etc.)
    with install + credential status, so the user knows what's ready."""
    from jaeger_os.core.tools.plugins import list_plugins
    result = list_plugins()
    plugins = result.get("plugins") or []
    if not plugins:
        ctx.console.print("[dim]No plugins found.[/]")
        return SlashResult()
    table = Table(show_header=True, header_style="bold cyan")
    table.add_column("Plugin")
    table.add_column("Status")
    table.add_column("Description")
    for p in plugins:
        desc = (p.get("description") or "").split("\n")[0][:60]
        table.add_row(p["name"], p["status"], desc)
    ctx.console.print(table)
    return SlashResult()


# ── Goal (Claude-Code-style /goal) ──────────────────────────────────


_GOAL_CLEAR_ALIASES = {"clear", "stop", "off", "reset", "none", "cancel"}


def _goal(ctx: SlashContext, args: str) -> SlashResult:
    """``/goal``              show active goal status + most recent eval reason
       ``/goal <condition>``  set a new completion condition
       ``/goal clear``        clear the active goal (aliases: stop, off, reset, none, cancel)
    """
    from jaeger_os.main import clear_goal, get_goal, set_goal

    body = args.strip()

    # ── Clear path ──
    if body.lower() in _GOAL_CLEAR_ALIASES:
        prior = clear_goal()
        if prior is None:
            ctx.console.print("[dim]No active goal to clear.[/]")
        else:
            ctx.console.print(
                f"[yellow]Cleared goal:[/] {prior.condition!r} "
                f"(ran {prior.turns_evaluated} turn(s), "
                f"{prior.elapsed_s():.0f}s)"
            )
        return SlashResult()

    # ── Status path ──
    if not body:
        goal = get_goal()
        if goal is None:
            ctx.console.print(
                "[dim]No active goal. Set one with [bold]/goal <condition>[/].[/]"
            )
            return SlashResult()
        table = Table(show_header=False, box=None)
        table.add_column(style="bold cyan")
        table.add_column()
        table.add_row("Condition", goal.condition)
        table.add_row("Running for", f"{goal.elapsed_s():.0f}s")
        table.add_row("Turns evaluated", str(goal.turns_evaluated))
        table.add_row("Tokens (eval)", str(goal.tokens_spent))
        table.add_row("Max iterations", str(goal.max_iterations))
        if goal.last_reason:
            table.add_row("Last eval", goal.last_reason)
        if goal.achieved:
            table.add_row("[green]Achieved[/]", "yes")
        ctx.console.print(table)
        return SlashResult()

    # ── Set path ──
    if len(body) > 4000:
        ctx.console.print(
            f"[red]Goal condition too long ({len(body)} chars; max 4000).[/]"
        )
        return SlashResult()
    goal = set_goal(body)
    ctx.console.print(
        f"[green]Goal set:[/] {goal.condition!r}\n"
        f"[dim]The TUI will run an evaluator after each turn until the "
        f"condition is met or {goal.max_iterations} turns elapse. Type "
        f"[bold]/goal clear[/] to stop early.[/]"
    )
    # Return a special marker the REPL reads to fire the FIRST turn
    # immediately using the condition itself as the prompt (matches
    # Claude Code's behavior: "Setting a goal starts a turn immediately").
    return SlashResult(message="", quit=False, extras={"goal_just_set": True})


# ── Deep Think ──────────────────────────────────────────────────────


def _deep_think_queue(ctx: SlashContext):
    """Build the DeepThinkQueue for the active instance."""
    from jaeger_os.core.deep_think import queue_for_layout
    from jaeger_os.core.instance import InstanceLayout
    import pathlib
    layout = InstanceLayout(root=pathlib.Path(str(ctx.instance_dir)))
    return queue_for_layout(layout)


def _deepthink(ctx: SlashContext, args: str) -> SlashResult:
    """``/deepthink``                  show mode + queue status
       ``/deepthink add <task>``       queue a skill-development job
       ``/deepthink list``             list every queued task
       ``/deepthink approve <id>``     approve an agent-proposed task
       ``/deepthink start``            enter Deep Think now (swap to coder model)
       ``/deepthink stop``             (only meaningful mid-loop; Ctrl-C also works)
    """
    parts = args.strip().split(None, 1)
    sub = parts[0].lower() if parts else ""
    rest = parts[1].strip() if len(parts) > 1 else ""

    try:
        queue = _deep_think_queue(ctx)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Deep Think unavailable:[/] {exc}")
        return SlashResult()

    # ── add ──
    if sub == "add":
        if not rest:
            ctx.console.print("[yellow]Usage:[/] /deepthink add <task description>")
            return SlashResult()
        task = queue.add(rest, source="user")
        ctx.console.print(
            f"[green]Queued[/] [{task.id}] {task.description}\n"
            f"[dim]Run [bold]/deepthink start[/] to work the queue.[/]"
        )
        return SlashResult()

    # ── list ──
    if sub in ("list", "ls"):
        tasks = queue.all_tasks()
        if not tasks:
            ctx.console.print("[dim]Deep Think queue is empty.[/]")
            return SlashResult()
        table = Table(show_header=True, header_style="bold cyan")
        table.add_column("ID")
        table.add_column("Status")
        table.add_column("Src")
        table.add_column("Task")
        for tk in tasks:
            status = tk.status
            if tk.status == "pending" and not tk.approved:
                status = "needs-approval"
            table.add_row(tk.id, status, tk.source,
                          tk.description[:60] + ("…" if len(tk.description) > 60 else ""))
        ctx.console.print(table)
        return SlashResult()

    # ── approve ──
    if sub == "approve":
        if not rest:
            ctx.console.print("[yellow]Usage:[/] /deepthink approve <task-id>")
            return SlashResult()
        task = queue.approve(rest)
        if task is None:
            ctx.console.print(f"[red]No task with id {rest!r}.[/]")
        else:
            ctx.console.print(f"[green]Approved[/] [{task.id}] {task.description}")
        return SlashResult()

    # ── start ──
    if sub == "start":
        nxt = queue.next_pending()
        if nxt is None:
            summary = queue.summary()
            if summary["awaiting_approval"]:
                ctx.console.print(
                    f"[yellow]Nothing approved to work.[/] "
                    f"{summary['awaiting_approval']} task(s) await approval — "
                    "use [bold]/deepthink approve <id>[/]."
                )
            else:
                ctx.console.print(
                    "[dim]Deep Think queue is empty. Add a task with "
                    "[bold]/deepthink add <task>[/] first.[/]"
                )
            return SlashResult()
        # Signal the REPL to enter the Deep Think loop.
        return SlashResult(extras={"deep_think_start": True})

    if sub == "stop":
        ctx.console.print(
            "[dim]Deep Think only runs inside its work loop — press "
            "Ctrl-C during the loop to interrupt and return to realtime.[/]"
        )
        return SlashResult()

    # ── status (no subcommand) ──
    summary = queue.summary()
    table = Table(show_header=False, box=None)
    table.add_column(style="bold cyan")
    table.add_column()
    table.add_row("Queue total", str(summary["total"]))
    table.add_row("Pending (ready)",
                  str(summary["pending"] - summary["awaiting_approval"]))
    table.add_row("Awaiting approval", str(summary["awaiting_approval"]))
    table.add_row("Done", str(summary["done"]))
    table.add_row("Failed", str(summary["failed"]))
    ctx.console.print(table)
    ctx.console.print(
        "[dim]/deepthink add <task> · /deepthink list · "
        "/deepthink start · Ctrl-C interrupts the loop[/]"
    )
    return SlashResult()


def _board_for_ctx(ctx: SlashContext):
    """Build the kanban Board for the active instance."""
    import pathlib

    from jaeger_os.core.board import board_for_layout
    from jaeger_os.core.instance import InstanceLayout
    layout = InstanceLayout(root=pathlib.Path(str(ctx.instance_dir)))
    return board_for_layout(layout)


_BOARD_COLUMN_STYLE = {
    "backlog": "dim", "ready": "cyan", "in_progress": "bold yellow",
    "blocked": "red", "done": "green",
}


def _board(ctx: SlashContext, args: str) -> SlashResult:
    """``/board``                  show the kanban board
       ``/board add <title>``      add a card (straight to ready)
       ``/board approve <id>``     approve a proposed card (backlog → ready)
       ``/board done <id>``        mark a card done
       ``/board block <id>``       mark a card blocked
       ``/board move <id> <col>``  move a card to any column
    """
    from jaeger_os.core.board import COLUMNS

    parts = args.strip().split(None, 2)
    sub = parts[0].lower() if parts else ""
    try:
        board = _board_for_ctx(ctx)
    except Exception as exc:  # noqa: BLE001
        ctx.console.print(f"[red]Board unavailable:[/] {exc}")
        return SlashResult()

    # ── add ──
    if sub == "add":
        title = args.strip()[3:].strip()
        if not title:
            ctx.console.print("[yellow]Usage:[/] /board add <card title>")
            return SlashResult()
        card = board.add(title, column="ready", source="user", created_by="user")
        ctx.console.print(f"[green]Added[/] [{card.id}] {card.title} → ready")
        return SlashResult()

    # ── id-taking subcommands ──
    if sub in ("approve", "done", "block", "move"):
        rest = parts[1] if len(parts) > 1 else ""
        if not rest:
            ctx.console.print(f"[yellow]Usage:[/] /board {sub} <card_id>"
                              + (" <column>" if sub == "move" else ""))
            return SlashResult()
        card = board.get(rest)
        if card is None:
            ctx.console.print(f"[red]No card[/] {rest!r}")
            return SlashResult()
        if sub == "approve":
            if card.column != "backlog":
                ctx.console.print(f"[dim]{rest} is already past backlog "
                                  f"({card.column}).[/]")
            else:
                board.move(rest, "ready")
                ctx.console.print(f"[green]Approved[/] {rest} → ready")
        elif sub == "done":
            board.move(rest, "done")
            ctx.console.print(f"[green]Done[/] {rest}")
        elif sub == "block":
            board.move(rest, "blocked")
            ctx.console.print(f"[red]Blocked[/] {rest}")
        else:  # move
            col = parts[2].strip().lower() if len(parts) > 2 else ""
            if col not in COLUMNS:
                ctx.console.print(f"[yellow]Column must be one of:[/] "
                                  f"{', '.join(COLUMNS)}")
            else:
                board.move(rest, col)
                ctx.console.print(f"[green]Moved[/] {rest} → {col}")
        return SlashResult()

    # ── show the board (no subcommand) ──
    summary = board.summary()
    if not summary.get("total"):
        ctx.console.print("[dim]The board is empty. "
                          "[bold]/board add <title>[/] to start.[/]")
        return SlashResult()
    for col in COLUMNS:
        cards = board.list(column=col)
        style = _BOARD_COLUMN_STYLE.get(col, "white")
        header = Text()
        header.append(f"▼ {col}", style=f"bold {style}")
        header.append(f"  ({len(cards)})", style="dim")
        ctx.console.print(header)
        for c in cards:
            tag = f" [dim]{','.join(c.tags)}[/]" if c.tags else ""
            ctx.console.print(f"  [dim]{c.id}[/]  {c.title}{tag}")
        if not cards:
            ctx.console.print("  [dim]—[/]")
    ctx.console.print(
        "[dim]/board add · /board approve <id> · /board done <id> · "
        "/board move <id> <col>[/]"
    )
    return SlashResult()


# ── Registry ─────────────────────────────────────────────────────────


REGISTRY: tuple[SlashCommand, ...] = (
    SlashCommand("help",      "show this command list", _help),
    SlashCommand("tools",     "list available agent tools by category", _tools),
    SlashCommand("facts",     "list stored facts (memory)", _facts),
    SlashCommand("instance",  "show active instance; `/instance <name>` to hot-switch", _instance),
    SlashCommand("instances", "list every available instance", _instances),
    SlashCommand("model",     "show active model", _model),
    SlashCommand("models",    "list registered models with cache status", _models),
    SlashCommand("download",  "`/download <name>` — fetch a model from HF Hub", _download),
    SlashCommand("plugins",   "list bundled plugins with setup status", _plugins),
    SlashCommand("goal",      "show/set/clear an autonomous completion condition (Claude-Code-style)", _goal),
    SlashCommand("deepthink", "autonomous skill-development mode: add/list/approve/start", _deepthink),
    SlashCommand("board",     "kanban task board: show/add/approve/done/move", _board),
    SlashCommand("reset",     "(placeholder) reset session state", _reset),
    SlashCommand("quit",      "exit the TUI", _quit),
)
_BY_NAME: dict[str, SlashCommand] = {c.name: c for c in REGISTRY}


def is_slash(line: str) -> bool:
    return line.strip().startswith("/")


def dispatch(line: str, ctx: SlashContext) -> SlashResult:
    """Run a slash command. Unknown commands print a hint and return a
    no-op SlashResult (REPL continues). Args (everything after the
    command name) are forwarded to the handler as a single string."""
    parts = line.strip().lstrip("/").split(None, 1)
    name = parts[0].lower() if parts else ""
    args = parts[1] if len(parts) > 1 else ""
    cmd = _BY_NAME.get(name)
    if cmd is None:
        ctx.console.print(
            f"[yellow]Unknown slash command:[/] /{name}.  Try [bold]/help[/]."
        )
        return SlashResult()
    return cmd.handler(ctx, args)
