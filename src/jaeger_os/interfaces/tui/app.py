"""Jaeger-OS TUI app — REPL loop with hermes-agent-inspired chrome.

Parallel implementation to
:mod:`jaeger_os.instance.lilith.interfaces.tui.app`. Same
hermes-agent-shaped surface (banner / boot panel / slash commands /
status bar / ruminating spinner) so users get a consistent look
regardless of which instance they're driving.

The agent path boots through :func:`jaeger_os.main.boot_for_tui` —
the same instance resolve → manifest gate → lock → bind tools →
load model → prewarm flow ``python -m jaeger_os`` uses, minus the
cron runner and MCP/thinking extensions (the TUI keeps it minimal).
"""

from __future__ import annotations

import asyncio
import queue
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.padding import Padding
from rich.rule import Rule
from rich.text import Text

from jaeger_os import __version__ as JAEGER_VERSION

from .banner import JAEGER_ASCII, TAGLINE
from .ptk_input import CTRL_C, build_session, read_prompt
from .slash_commands import SlashContext, dispatch, is_slash
from .voice_session import is_exit_phrase
from .status import boot_panel, make_session_id
from .theme import ACCENT, ACCENT_BOLD, ACCENT_PTK


# Frames for the live "ruminating" spinner shown in the prompt_toolkit
# bottom toolbar while a turn runs on the worker thread.
_SPINNER_FRAMES = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"

# Queue sentinels. _WORKER_SHUTDOWN tells the turn worker to exit;
# "__deepthink__" as a turn source routes the worker into Deep Think.
_WORKER_SHUTDOWN = object()
_DEEPTHINK_SOURCE = "__deepthink__"

# Slash commands that swap the model / instance / pipeline out from
# under a turn — refused while one is running (Ctrl-C or wait first).
_TURN_UNSAFE_SLASH = frozenset({
    "model", "instance", "reboot", "shutdown", "factoryreset",
    "download", "deepthink",
})


def _kfmt(n: int) -> str:
    """Compact token count: 27800 → '27.8K', 980 → '980'."""
    if n >= 1000:
        return f"{n / 1000:.1f}K"
    return str(int(n))


def _dur(seconds: float) -> str:
    """Compact duration for the status bar: '4m', '1h 04m', '12s'."""
    s = int(seconds)
    if s < 60:
        return f"{s}s"
    if s < 3600:
        return f"{s // 60}m"
    return f"{s // 3600}h {s % 3600 // 60:02d}m"


# Typed phrases that enter continuous voice mode instead of being sent
# to the agent (which would otherwise call the one-shot `listen` tool).
# Gated on a short line so a coding request that merely mentions the
# microphone ("write code to turn on the mic") doesn't trip it.
_VOICE_TRIGGER_RE = re.compile(
    r"(turn on (the )?mic(rophone)?"
    r"|mic(rophone)? on\b"
    r"|enable (the )?mic(rophone)?"
    r"|voice (conversation|chat|mode)"
    r"|(start|enter|begin) voice"
    r"|have a voice (conversation|chat))",
    re.IGNORECASE,
)


def _wants_voice_mode(line: str) -> bool:
    """True when a typed line is a request to enter voice conversation."""
    line = (line or "").strip()
    return len(line) <= 80 and bool(_VOICE_TRIGGER_RE.search(line))


# Resolve default instance dir the same way jaeger.core.prompts does.
_DEFAULT_INSTANCE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "instance" / "default"
)


# ── Permission confirmation ──────────────────────────────────────────


class _TuiConfirmationProvider:
    """Confirmation prompt for the TUI.

    A tier-gated tool (computer_use, run_in_venv, install_package, …)
    asks the user for approval through this. It suspends the turn's
    spinner so the prompt is visible, asks via the Rich console, then
    resumes.

    Grants are **per skill** (:class:`~jaeger_os.core.permissions.PermissionGrants`):
    *yes* approves the skill for the rest of the session, *always*
    persists it to ``<instance>/permissions.json`` so it never asks
    again across restarts. An already-granted skill never re-prompts —
    a 'yes' is a yes.
    """

    def __init__(self, tui: "JaegerTUI") -> None:
        from jaeger_os.core.permissions import PermissionGrants
        self._tui = tui
        # 'yes' holds for the session, 'always' persists to
        # <instance>/permissions.json — loaded for the booted instance.
        self._grants = PermissionGrants.load(getattr(tui, "instance_dir", None))

    def confirm(self, request: Any) -> bool:
        skill = getattr(request, "skill", "") or ""
        if self._grants.is_granted(skill):
            return True
        # The turn runs on the worker thread; the prompt below needs
        # stdin, which the main thread's live input loop owns. Route it
        # through _run_on_terminal so prompt_toolkit suspends the input
        # line for the duration of the question.
        return self._tui._run_on_terminal(lambda: self._ask(request, skill))

    def _ask(self, request: Any, skill: str) -> bool:
        """The actual y/N/a question. Runs with exclusive terminal
        access (see :meth:`JaegerTUI._run_on_terminal`)."""
        console = self._tui.console
        tier = getattr(request.tier, "name", str(request.tier))
        console.print()
        console.print(
            f"[bold yellow]⚠ permission needed[/]  "
            f"[cyan]{request.skill}.{request.operation}[/]  [dim]{tier}[/]"
        )
        if request.summary:
            console.print(f"  [dim]{request.summary}[/]")
        try:
            ans = console.input(
                f"  allow?  [bold]y[/]es (rest of session) / [bold]N[/]o / "
                f"[bold]a[/]lways (remember [cyan]{skill or 'this'}[/]): "
            ).strip().lower()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return False
        # First-letter match: "always"/"allow"/"a" persist the grant;
        # "yes"/"y" grant it for the session.
        if ans.startswith("a"):
            self._grants.grant_persistent(skill)
            console.print(
                f"  [green]✓ remembered[/] — [cyan]{skill or 'this'}[/] "
                f"won't ask again"
            )
            return True
        if ans.startswith("y"):
            self._grants.grant_session(skill)
            return True
        return False


# ── App ──────────────────────────────────────────────────────────────


class JaegerTUI:
    """The interactive TUI driver for Jaeger-OS.

    Owns the Rich Console, the agent (lazy-built on first turn so
    `--banner-only` is cheap), the slash-command context, and the
    session counters. Mirrors :class:`lilith.interfaces.tui.app.LilithTUI`.
    """

    def __init__(
        self,
        *,
        instance_dir: Path | None = None,
        model_name: str = "gemma-4-26B-A4B-it",
        version: str = JAEGER_VERSION,
        skip_model: bool = False,
    ) -> None:
        self.console = Console()
        self.instance_dir = instance_dir or _DEFAULT_INSTANCE_DIR
        self.model_name = model_name
        self.version = version
        self.session_id = make_session_id()
        self.skip_model = skip_model
        self._agent = None
        self._client = None
        self._boot = None  # TUIBootResult from jaeger_os.main.boot_for_tui
        self._voice: Any = None  # VoiceController — the always-on mic, or None
        self._ptk_session: Any = None  # prompt_toolkit PromptSession (lazy)
        self._statusbar_on = True  # bottom status bar visible (/statusbar)
        self._started_at = time.perf_counter()
        self._context_tokens = 0
        self._context_max = 8192
        self._last_turn_s = 0.0   # wall time of the most recent turn
        self._turn_count = 0      # turns run this session (for /usage)
        self._last_answer = ""    # most recent reply text (for /copy)
        # ── Concurrent turn worker (hermes-style: type while it works) ──
        # Turns run on a background thread so the input line stays live.
        self._turn_queue: queue.Queue = queue.Queue()
        self._turn_running = threading.Event()   # set while a turn executes
        self._worker_stop = threading.Event()    # signals the worker to exit
        self._worker: threading.Thread | None = None
        self._turn_started_at = 0.0              # for the live toolbar timer
        self._current_activity = ""             # live spinner label
        self._busy_mode = "interrupt"           # /busy: interrupt|queue|steer
        self._ptk_loop: Any = None              # prompt_toolkit's asyncio loop
        self._last_activity = time.monotonic()  # for auto-idle Deep Think
        self._idle_fired = False
        self._voice_thread: threading.Thread | None = None
        self._voice_stop = threading.Event()
        self.slash_ctx = SlashContext(
            console=self.console,
            instance_dir=self.instance_dir,
            tui=self,  # let /instance <name> + /download reach back here
        )

    # ── Boot screen ─────────────────────────────────────────────────

    def render_boot(self) -> None:
        """Print the banner + tagline + boot status panel. One-shot."""
        self.console.print(Text(JAEGER_ASCII, style=ACCENT_BOLD))
        self.console.print(Text(TAGLINE, style=f"dim {ACCENT}"))
        self.console.print()
        self.console.print(boot_panel(
            version=self.version,
            instance_name=self.instance_dir.name,
            model_name=self.model_name,
            session_id=self.session_id,
            instance_dir=self.instance_dir,
        ))
        self.console.print()

    def _print_ready_hint(self) -> None:
        """The 'type a prompt' hint. Printed *after* the eager boot so it
        only appears once the Jaeger is actually operational — not while
        the model is still loading."""
        self.console.print(
            "[dim]Type a prompt, or [bold]/help[/] for slash commands.[/]"
        )
        self.console.print()

    # ── Agent (lazy) ────────────────────────────────────────────────

    def _ensure_agent(self) -> Any:
        """Boot the jaeger pipeline on first use. Cached for the
        lifetime of the TUI; cleanup runs in :meth:`repl`'s finally."""
        if self._client is not None or self.skip_model:
            return self._client
        from jaeger_os.main import boot_for_tui

        with self.console.status(
            f"[{ACCENT_BOLD}]booting jaeger…[/]", spinner="dots",
        ):
            self._boot = boot_for_tui(instance_name=self.instance_dir.name)
        self._client = self._boot.client
        # Refresh status panel state with what the pipeline picked
        # (the instance dir may have been wizard-created on first run;
        # the brain may be an external model rather than local Gemma).
        self.instance_dir = self._boot.layout.root
        self.model_name = getattr(self._client, "model_name", self.model_name)
        self._install_confirmations()
        return self._client

    def _install_confirmations(self) -> None:
        """Install the permission confirmation provider for the TUI.

        'confirm' mode → the spinner-aware prompt; 'allow' mode →
        auto-approve. The mode is ``config.permissions.mode``, chosen at
        first-boot setup and persisted, so the posture survives restarts."""
        from jaeger_os.core.permissions import (
            AllowAllProvider, PermissionPolicy, install_policy,
        )
        from jaeger_os.main import _pipeline
        cfg = _pipeline.get("config")
        mode = getattr(getattr(cfg, "permissions", None), "mode", "confirm")
        provider = (AllowAllProvider() if mode == "allow"
                    else _TuiConfirmationProvider(self))
        install_policy(PermissionPolicy(confirmation=provider))
        # Live tool-progress: the agent loop calls this per tool call so
        # the TUI can show ``┊`` activity lines + the toolbar spinner.
        _pipeline["tool_event_cb"] = self._on_tool_event

    def _boot_eager(self) -> None:
        """Boot the pipeline at launch so the Jaeger is operational the
        moment the prompt appears — no waiting for the first message to
        trigger the model load + warmups.

        A failure here is non-fatal: it is printed and ``_ensure_agent``
        will retry on the first turn, so a transient boot error never
        leaves the user staring at a dead REPL."""
        if self.skip_model:
            return
        try:
            self._ensure_agent()
        except Exception as exc:  # noqa: BLE001
            self.console.print(
                f"[red]Boot failed:[/] {exc}\n"
                "[dim]Will retry on your first message.[/]"
            )
            return
        # Voice is on by default — a Jaeger is embodied and always
        # listens. Bring the mic up now so it's live the instant the
        # prompt appears. A failure here is non-fatal (text still works).
        try:
            if self._voice_config().enabled:
                self.start_voice()
        except Exception as exc:  # noqa: BLE001
            self.console.print(f"[dim](voice didn't start: {exc})[/]")

    def switch_instance(self, name: str) -> None:
        """Hot-switch the running TUI to a different instance.

        Tears down the current llama-cpp client + instance lock, then
        boots ``name`` via :func:`boot_for_tui`. Wall cost is ~5-10s
        (Gemma reload). Called by ``/instance <name>``; raises on any
        boot error so the slash handler can surface it."""
        import gc

        from jaeger_os.main import boot_for_tui
        from .status import make_session_id

        # Release current boot before allocating the new one. On
        # unified-memory Macs we MUST drop the prior llama-cpp client
        # first or peak RSS doubles for a moment.
        if self._boot is not None:
            try:
                self._boot.cleanup()
            except Exception:
                pass
        self._boot = None
        self._client = None
        self._agent = None
        gc.collect()

        # Boot the new instance. Any failure propagates so the slash
        # handler can print it and the user can pick another instance.
        self._boot = boot_for_tui(instance_name=name)
        self._client = self._boot.client
        self.instance_dir = self._boot.layout.root
        self.model_name = getattr(self._client, "model_name", self.model_name)
        self._install_confirmations()
        self.session_id = make_session_id()
        # Slash context carries instance_dir — rebuild so /facts, /instance,
        # etc. see the new path. ``tui=self`` preserved so further
        # switches still work.
        self.slash_ctx = SlashContext(
            console=self.console,
            instance_dir=self.instance_dir,
            tui=self,
        )

    # ── Turn ────────────────────────────────────────────────────────

    def run_turn(self, user_text: str, *, source: str = "text") -> None:
        """Run one user turn — interruptibly.

        A turn no longer locks up the TUI: **Ctrl-C aborts the turn**
        (and returns to the prompt instead of quitting), and in a voice
        turn **speaking aborts it too** — the agent loop checks a cancel
        flag between steps and halts gracefully. ``source`` is "text"
        or "voice"."""
        client = self._ensure_agent()
        if client is None:
            self.console.print(
                "[yellow]Agent not initialized (skip_model=True).[/]"
            )
            return

        from jaeger_os.main import begin_turn_cancel_scope, request_turn_cancel

        cancel = begin_turn_cancel_scope()
        # Voice turn: sustained user speech during the turn trips the
        # cancel flag, so the user can talk over a long 'ruminating'.
        armed = (source == "voice" and self._voice is not None
                 and self._voice.running)
        if armed:
            self._voice.arm_interrupt(cancel)
        try:
            if source == "voice":
                self._run_voice_turn(client, user_text)
            else:
                self._run_text_turn(client, user_text, source=source)
        except KeyboardInterrupt:
            # Ctrl-C aborts THIS turn, not the whole TUI. Setting the
            # flag too lets the agent loop unwind cleanly when it is
            # between steps rather than mid-decode.
            request_turn_cancel()
            self.console.print("\n[yellow]⨯ stopped — back to you.[/]")
        finally:
            if armed:
                self._voice.disarm_interrupt()

    # ── Turn chrome (hermes-style) ──────────────────────────────────

    def _agent_name(self) -> str:
        """The instance's display name for the answer-panel title.
        Read live from identity.yaml so a mid-session `set_name` shows
        up immediately; falls back to 'Jaeger'."""
        return self._resolve_instance_name() or "Jaeger"

    def _render_turn_header(self, user_text: str, *, source: str = "text") -> None:
        """The hermes-style turn separator — the user's message framed
        between two rules, on a bullet line (● typed, 🎙 spoken, ◎ goal).

        Built with :class:`Text.append` rather than Rich markup so a
        message containing ``[red]`` etc. can never inject styling."""
        self.console.print()
        self.console.print(Rule(style=ACCENT))
        glyph = {"voice": "🎙", "goal": "◎"}.get(source, "●")
        line = Text("  ")
        line.append(f"{glyph} ", style=ACCENT_BOLD)
        line.append(user_text.strip(), style="bold")
        self.console.print(line)
        self.console.print(Rule(style=ACCENT))

    def _render_answer(self, text: str, *, error: str | None = None) -> None:
        """Render the agent's reply hermes-style: a left-labelled top
        rule, the body indented into the chat column, a closing rule.

        Tool activity is shown live *during* the turn (see
        :meth:`_on_tool_event`), not here. The body is a plain
        :class:`Text` so the model's answer is never interpreted as Rich
        markup."""
        body = (error or text or "").strip()
        if not body:
            return
        is_err = error is not None
        if not is_err:
            self._last_answer = body   # for /copy
        accent = "red" if is_err else ACCENT
        label = Text(f" ✦ {'error' if is_err else self._agent_name()} ",
                     style=f"bold {accent}")
        self.console.print()
        self.console.print(Rule(label, align="left", style=accent))
        self.console.print()
        self.console.print(Padding(
            Text(body, style="red" if is_err else ""), (0, 2, 0, 4)))
        self.console.print()
        self.console.print(Rule(style=accent))

    # ── Live tool activity (during a turn) ──────────────────────────

    def _on_tool_event(self, phase: str, tool: str, detail: str,
                       elapsed: float) -> None:
        """Agent-loop callback — fired as a turn runs, once per tool.

        ``phase`` is "start" or "done". On start the bottom-toolbar
        spinner switches to the tool name; on done a ``┊`` activity line
        is printed into the scrollback with the elapsed time, hermes-
        style. Runs on the turn worker thread — the print scrolls above
        the live input line via ``patch_stdout``."""
        if phase == "start":
            self._current_activity = tool
            return
        # phase == "done"
        self._current_activity = "ruminating"
        from jaeger_os.main import _pipeline
        if not _pipeline.get("show_tool_activity", True):
            return
        line = Text("  ┊ ", style=ACCENT)
        line.append("🔧 ", style="")
        line.append(tool, style="cyan")
        if detail:
            line.append(f"  {detail}", style="dim")
        if elapsed > 0:
            line.append(f"  {elapsed:.1f}s", style="dim")
        self.console.print(line)

    def _refresh_context_estimate(self) -> None:
        """Update the context-token gauge from the session-history size
        — a chars/4 estimate. Rough, but it moves the bottom-bar gauge
        as the conversation grows, which is what the gauge is for."""
        try:
            from jaeger_os.main import (
                _DEFAULT_SESSION_KEY, _get_session_history, _pipeline,
            )
            history = _get_session_history(_DEFAULT_SESSION_KEY)
        except Exception:  # noqa: BLE001
            return
        chars = 0
        for msg in history:
            for part in getattr(msg, "parts", []):
                content = getattr(part, "content", None)
                if content:
                    chars += len(str(content))
        self._context_tokens = chars // 4
        try:
            cfg = _pipeline.get("config")
            ctx = int(getattr(getattr(cfg, "model", None), "ctx", 0) or 0)
            if ctx > 0:
                self._context_max = ctx
        except Exception:  # noqa: BLE001
            pass

    def _run_text_turn(
        self, client: Any, user_text: str, *, source: str = "text",
    ) -> None:
        """A typed (or goal-loop) turn — runs the unified turn and
        renders the reply in hermes-style chrome (rule-framed user
        message, live ``┊`` tool lines, the answer in a labelled box).

        The "ruminating" spinner + live counters live in the
        prompt_toolkit bottom toolbar (see :meth:`_bottom_toolbar`), not
        a Rich ``Live`` — a ``Live`` on this worker thread would fight
        the input line the main thread renders. ``source`` is "text" or
        "goal"."""
        from jaeger_os.main import _DEFAULT_SESSION_KEY, run_for_voice

        self._render_turn_header(user_text, source=source)
        started = time.perf_counter()
        result = run_for_voice(client, user_text,
                               session_key=_DEFAULT_SESSION_KEY)
        self._last_turn_s = time.perf_counter() - started
        self._turn_count += 1
        self._refresh_context_estimate()
        self._render_answer(result.get("text") or "",
                            error=result.get("error"))

    # ── Voice conversation ──────────────────────────────────────────

    def _resolve_instance_name(self) -> str | None:
        """The instance's display name (identity.yaml ``name``) — used as
        the voice wake word. None on any read error."""
        try:
            from jaeger_os.core.instance import InstanceLayout
            from jaeger_os.core.schemas import Identity, load_yaml
            layout = InstanceLayout(root=self.instance_dir)
            return load_yaml(layout.identity_path, Identity).name
        except Exception:  # noqa: BLE001
            return None

    def _voice_config(self) -> Any:
        """The active instance's VoiceConfig, read from the live pipeline
        config. Falls back to defaults (all on) if it can't be read."""
        from jaeger_os.core.schemas import VoiceConfig
        try:
            from jaeger_os.main import _pipeline
            cfg = _pipeline.get("config")
            return getattr(cfg, "voice", None) or VoiceConfig()
        except Exception:  # noqa: BLE001
            return VoiceConfig()

    def start_voice(self, *, announce: bool = True) -> None:
        """Bring the always-on mic online from the current VoiceConfig.
        No-op if it is already running; prints the reason if it can't."""
        if self._voice is not None and self._voice.running:
            if announce:
                self.console.print("[dim]🎙  mic is already on.[/]")
            return
        vc = self._voice_config()
        from .voice_session import VoiceController
        self._voice = VoiceController(
            self.console,
            wake_word=vc.wake_word,
            follow_up=vc.follow_up,
            barge_in=vc.barge_in,
            follow_up_seconds=vc.follow_up_seconds,
            wake_name=self._resolve_instance_name(),
        )
        if announce:
            self.console.print("[dim]🎙  bringing the mic online…[/]")
        if not self._voice.start():
            self._voice = None
            return
        # Spawn the mic poller so each committed phrase becomes a turn,
        # routed through the same busy-input rules as a typed line.
        self._voice_stop.clear()
        self._voice_thread = threading.Thread(
            target=self._voice_poll_loop, name="jaeger-voice", daemon=True)
        self._voice_thread.start()
        if announce:
            self._print_voice_banner()

    def _print_voice_banner(self) -> None:
        """One-line 'voice is on, here's how to use it' notice."""
        v = self._voice
        if v is None:
            return
        if v.wake_word:
            msg = (f"[bold green]🎙  voice on[/] — always listening. Say "
                   f"[bold]\"{v.wake_word_phrase}\"[/] to talk, or just type.")
        else:
            msg = ("[bold green]🎙  voice on[/] — always listening, no wake "
                   "word. Talk or type at any time.")
        if v.barge_in and not v.barge_in_live:
            msg += ("\n[dim](barge-in wanted but speexdsp is missing — the "
                    "mic pauses while I speak.)[/]")
        self.console.print(msg)

    def stop_voice(self) -> None:
        """Shut the mic down — poll thread first, then the controller.
        Idempotent; safe to call from the poll thread itself."""
        self._voice_stop.set()
        t = self._voice_thread
        if t is not None and t is not threading.current_thread():
            t.join(timeout=2.0)
        self._voice_thread = None
        if self._voice is not None:
            self._voice.stop()
            self._voice = None

    def apply_voice_setting(self, key: str, value: bool) -> str:
        """Toggle a voice setting, persist it to config.yaml, and apply
        it live (restarting the mic when the change needs a rebuild).
        Returns a short status line for the slash handler to print."""
        vc = self._voice_config()
        if key not in {"enabled", "wake_word", "follow_up", "barge_in"}:
            return f"[yellow]Unknown voice setting '{key}'.[/]"
        setattr(vc, key, value)
        self._persist_voice_config(vc)
        if key == "enabled":
            if value:
                self.start_voice()
            else:
                self.stop_voice()
        elif self._voice is not None and self._voice.running:
            # wake_word / barge_in are fixed when the STT is built;
            # follow_up is cheap but restart anyway for one clean path.
            self.stop_voice()
            self.start_voice()
        return f"[green]voice.{key}[/] → {'on' if value else 'off'}"

    def _persist_voice_config(self, vc: Any) -> None:
        """Write the VoiceConfig into the live config and config.yaml."""
        try:
            from jaeger_os.core.instance import InstanceLayout
            from jaeger_os.core.schemas import dump_yaml
            from jaeger_os.main import _pipeline
            cfg = _pipeline.get("config")
            if cfg is None:
                return
            cfg.voice = vc
            dump_yaml(InstanceLayout(root=self.instance_dir).config_path, cfg)
        except Exception as exc:  # noqa: BLE001
            self.console.print(
                f"[dim](couldn't persist voice settings: {exc})[/]"
            )

    def voice_status_text(self) -> str:
        """Render the current voice settings for `/voice` with no args."""
        vc = self._voice_config()
        live = self._voice is not None and self._voice.running

        def b(x: bool) -> str:
            return "[green]on[/]" if x else "[dim]off[/]"

        return "\n".join([
            f"[bold]Voice[/] — mic is "
            f"{'[green]live[/]' if live else '[dim]off[/]'}",
            f"  enabled    {b(vc.enabled)}   [dim]/voice on│off[/]",
            f"  wake word  {b(vc.wake_word)}   [dim]/voice wake on│off[/]",
            f"  follow-up  {b(vc.follow_up)}   [dim]/voice followup on│off[/]",
            f"  barge-in   {b(vc.barge_in)}   [dim]/voice bargein on│off[/]",
        ])

    def _run_voice_turn(self, client: Any, user_text: str) -> None:
        """A spoken turn: run the unified turn, render the same
        hermes-style chrome a typed turn gets, then speak the reply
        (barge-in aware) and open the follow-up window."""
        from jaeger_os.main import _DEFAULT_SESSION_KEY, run_for_voice

        self._render_turn_header(user_text, source="voice")
        started = time.perf_counter()
        result = run_for_voice(client, user_text,
                               session_key=_DEFAULT_SESSION_KEY)
        self._last_turn_s = time.perf_counter() - started
        self._turn_count += 1
        self._refresh_context_estimate()
        self._render_answer(result.get("text") or "",
                            error=result.get("error"))
        text = (result.get("text") or "").strip()
        v = self._voice
        if v is not None and v.running:
            if text and not result.get("spoke_via_tool"):
                v.speak(text)
            v.chime("followup")
            v.open_followup()

    # ── Goal loop ───────────────────────────────────────────────────

    def _session_transcript_tail(self, max_chars: int = 4000) -> str:
        """Serialize the recent session history into a plain-text
        transcript the goal evaluator can read. Pulls from the same
        ``cli`` session key ``run_command`` writes to."""
        from jaeger_os.main import _DEFAULT_SESSION_KEY, _get_session_history
        try:
            history = _get_session_history(_DEFAULT_SESSION_KEY)
        except Exception:
            return ""
        lines: list[str] = []
        for msg in history[-14:]:
            for part in getattr(msg, "parts", []):
                pk = getattr(part, "part_kind", None)
                content = getattr(part, "content", None)
                if pk == "user-prompt" and content:
                    lines.append(f"User: {content}")
                elif pk == "text" and content:
                    lines.append(f"Assistant: {content}")
                elif pk == "tool-return":
                    tn = getattr(part, "tool_name", "tool")
                    lines.append(f"[{tn} result]: {str(content)[:200]}")
        return "\n".join(lines)[-max_chars:]

    def _post_turn_goal_check(self) -> str | None:
        """After a turn, evaluate the active goal. Returns the prompt
        for the next auto-fired turn, or None when there's no goal /
        the goal is met / the iteration cap is hit."""
        from jaeger_os.main import clear_goal, evaluate_goal, get_goal

        goal = get_goal()
        if goal is None or goal.achieved:
            return None
        transcript = self._session_transcript_tail()
        # No Rich status spinner here — the goal check runs on the turn
        # worker thread, where a Live fights the input line. The bottom
        # toolbar shows "evaluating goal" while this runs.
        met, reason = evaluate_goal(self._client, goal, transcript)
        goal.turns_evaluated += 1
        goal.last_reason = reason
        if met:
            goal.achieved = True
            self.console.print(
                f"[bold green]◎ goal achieved[/] after "
                f"{goal.turns_evaluated} turn(s), {goal.elapsed_s():.0f}s — "
                f"{reason}"
            )
            clear_goal()
            return None
        if goal.turns_evaluated >= goal.max_iterations:
            self.console.print(
                f"[yellow]◎ goal stopped[/] — hit the "
                f"{goal.max_iterations}-turn cap without meeting the "
                f"condition. Last eval: {reason}"
            )
            clear_goal()
            return None
        self.console.print(
            f"[dim]◎ goal not met "
            f"({goal.turns_evaluated}/{goal.max_iterations}) — {reason}[/]"
        )
        # The evaluator's reason becomes the next turn's directive.
        return reason

    # ── Deep Think ──────────────────────────────────────────────────

    def run_deep_think(self) -> None:
        """Enter Deep Think mode: swap to the coder model, work the
        queued skill-development tasks one at a time, swap back to the
        realtime model when the queue drains or the user hits Ctrl-C.

        See docs/deep_think_design.md. The model swap means only one
        model is RAM-resident at a time. Ctrl-C is the wake interrupt:
        the in-progress task is flipped back to ``pending`` so it
        resumes next time, and the realtime model is reloaded."""
        from jaeger_os.main import run_command, switch_model
        from jaeger_os.core.deep_think import queue_for_layout
        from jaeger_os.core.instance import InstanceLayout
        from jaeger_os.core.model_resolver import (
            DEFAULT_CODER_MODEL,
            DEFAULT_MODEL,
        )
        from jaeger_os.core.reflection import reflect_on_task, save_reflection

        # The pipeline must be booted (config/lock/layout) before we can
        # swap models — _ensure_agent does that on first use.
        if self._ensure_agent() is None:
            self.console.print("[yellow]Agent not initialized.[/]")
            return

        layout = InstanceLayout(root=self.instance_dir)
        queue = queue_for_layout(layout)
        if queue.next_pending() is None:
            self.console.print("[dim]Deep Think queue is empty.[/]")
            return

        # ── swap in the coder model ──
        self.console.print(
            "[bold yellow]◎ entering Deep Think[/] — swapping to the "
            "coder model. The robot won't be conversational until it "
            "swaps back. [dim](Ctrl-C interrupts.)[/]"
        )
        self._client = None  # drop ref so the old model frees before reload
        try:
            # Plain print, not a Rich status spinner — Deep Think runs on
            # the turn worker thread, and a Live there fights the
            # main-thread input line.
            self.console.print("[yellow]◎ loading coder model…[/]")
            self._client = switch_model(DEFAULT_CODER_MODEL)
        except Exception as exc:  # noqa: BLE001
            self.console.print(
                f"[red]Couldn't load coder model ({DEFAULT_CODER_MODEL}):[/] "
                f"{exc}\n[dim]Staying on the realtime model.[/]"
            )
            # Make sure we're back on a working realtime client.
            try:
                self._client = switch_model(DEFAULT_MODEL)
            except Exception:
                pass
            return

        completed = 0
        failed = 0
        try:
            while True:
                task = queue.next_pending()
                if task is None:
                    break
                queue.mark_in_progress(task.id)
                self.console.print(
                    f"[cyan]◎ deep think ›[/] {task.description}"
                )
                outcome = "done"
                try:
                    directive = (
                        f"You are in Deep Think mode — autonomous skill "
                        f"development. Complete this task fully, writing all "
                        f"needed files into the skills/ directory and "
                        f"installing any dependencies with install_package:\n\n"
                        f"{task.description}"
                    )
                    run_command(self._client, directive,
                                session_key=f"deepthink_{task.id}")
                    queue.mark_done(task.id, "completed in Deep Think")
                    completed += 1
                    self.console.print(f"[green]  ✓ done[/] [{task.id}]")
                except KeyboardInterrupt:
                    raise
                except Exception as exc:  # noqa: BLE001
                    outcome = f"failed: {exc}"
                    queue.mark_failed(task.id, str(exc))
                    failed += 1
                    self.console.print(f"[red]  ✗ failed[/] [{task.id}]: {exc}")
                # After-action reflection — extract a durable lesson and
                # persist it (chronological log + episodic memory).
                # Best-effort; a reflection failure never breaks the loop.
                try:
                    reflection = reflect_on_task(
                        self._client, task.description, outcome,
                    )
                    if reflection:
                        save_reflection(layout, task.description,
                                        outcome, reflection)
                        self.console.print(
                            f"[dim]  ↳ reflected: {reflection[:100]}[/]"
                        )
                except Exception:  # noqa: BLE001
                    pass
        except KeyboardInterrupt:
            n = queue.reset_in_progress()
            self.console.print(
                f"\n[yellow]◎ Deep Think interrupted[/] — "
                f"{n} task(s) flipped back to pending for next time."
            )
        finally:
            # ── swap the realtime model back in ──
            self.console.print(
                "[bold yellow]◎ leaving Deep Think[/] — reloading the "
                "realtime model…"
            )
            self._client = None
            try:
                self.console.print("[yellow]◎ loading realtime model…[/]")
                # switch_model rebuilds the agent, which re-runs the
                # skill loader — so anything Deep Think authored is now
                # live for the realtime model.
                self._client = switch_model(DEFAULT_MODEL)
            except Exception as exc:  # noqa: BLE001
                self.console.print(
                    f"[red]Failed to reload realtime model:[/] {exc}"
                )

        self.console.print(
            f"[green]◎ Deep Think complete[/] — {completed} done, "
            f"{failed} failed. New skills (if any) are now available."
        )

    # ── Auto-idle ───────────────────────────────────────────────────

    def _auto_idle_seconds(self) -> int:
        """Idle window (in seconds) before the TUI auto-enters Deep
        Think, from the instance config's ``deep_think.auto_idle_minutes``.
        0 (default) ⇒ auto-idle off. Reads the live pipeline config so
        it reflects the booted instance."""
        try:
            from jaeger_os.main import _pipeline
            cfg = _pipeline.get("config")
            if cfg is None:
                return 0
            return int(cfg.deep_think.auto_idle_minutes) * 60
        except Exception:  # noqa: BLE001
            return 0

    def _status_line(self) -> str:
        """The hermes-style status bar content (no chrome) —
        ``✦ model │ 27.8K/262K │ [█░░░] 11% │ 4m │ ⏲ 23s``. Rendered
        into the prompt by :meth:`_prompt_message`."""
        running = self._turn_running.is_set()
        segs: list[str] = []
        # Live turn spinner — first segment while the agent works.
        if running:
            frame = _SPINNER_FRAMES[int(time.time() * 8) % len(_SPINNER_FRAMES)]
            segs.append(f"{frame} {self._current_activity or 'ruminating'}")
        # Model.
        segs.append(f"✦ {self.model_name}")
        # Context gauge — k-formatted count, a 10-cell bar, a percentage.
        mx = max(1, self._context_max)
        pct = min(100, int(self._context_tokens / mx * 100))
        fill = pct // 10
        bar = "█" * fill + "░" * (10 - fill)
        segs.append(f"{_kfmt(self._context_tokens)}/{_kfmt(mx)}")
        segs.append(f"[{bar}] {pct}%")
        # Uptime.
        segs.append(_dur(time.perf_counter() - self._started_at))
        # Response time — live elapsed while running, else the last turn.
        if running:
            segs.append(f"⏲ {time.perf_counter() - self._turn_started_at:.0f}s")
        elif self._last_turn_s > 0:
            segs.append(f"⏲ {self._last_turn_s:.0f}s")
        # Mic, only when live.
        if self._voice is not None and self._voice.running:
            segs.append("🎙 on")
        return "  │  ".join(segs)

    def _prompt_message(self) -> Any:
        """The prompt_toolkit prompt — the pinned status bar drawn a few
        lines above the ``❯`` input line, so the input is always the
        very last line on screen (hermes layout).

        Returned as a fragment list and re-evaluated every
        ``refresh_interval``, so the bar's spinner + timer animate. This
        callable runs inside prompt_toolkit's event loop, so it is also
        where that loop is captured for :meth:`_run_on_terminal`."""
        try:
            self._ptk_loop = asyncio.get_running_loop()
        except RuntimeError:
            pass
        frags: list[tuple[str, str]] = []
        if self._statusbar_on:
            import shutil
            width = max(20, shutil.get_terminal_size((80, 24)).columns)
            rule = "─" * width
            frags.append((f"fg:{ACCENT_PTK}", rule + "\n"))
            frags.append(("fg:ansibrightblack", "  " + self._status_line() + "\n"))
            frags.append((f"fg:{ACCENT_PTK}", rule + "\n"))
        frags.append((f"fg:{ACCENT_PTK} bold", "❯ "))
        return frags

    def _prompt_placeholder(self) -> Any:
        """Ghost hint shown in the empty input line — what Enter does
        mid-turn and the key shortcuts, hermes-style. Disappears the
        moment the user types."""
        return [(
            "fg:ansibrightblack",
            f"  msg → {self._busy_mode}   ·   /steer   ·   /busy   "
            "·   ^C interrupt",
        )]

    def _read_line(self) -> Any:
        """Read one line via the prompt_toolkit session — slash
        autocomplete, ghost-text, the pinned status bar, history.
        Returns the string, :data:`CTRL_C` on Ctrl-C, ``None`` on EOF."""
        if self._ptk_session is None:
            self._ptk_session = build_session()
        return read_prompt(self._ptk_session,
                           message=self._prompt_message,
                           placeholder=self._prompt_placeholder)

    # ── Turn worker (concurrent input) ──────────────────────────────

    def _run_on_terminal(self, func: Any) -> Any:
        """Run ``func()`` with exclusive terminal access — used by the
        turn worker thread when a tool needs to ask the user something.

        While a turn runs, the main thread sits in prompt_toolkit's
        ``prompt()`` and owns stdin. ``run_in_terminal`` (scheduled onto
        prompt_toolkit's loop) suspends the input line, runs ``func`` in
        a clean cooked-mode terminal, then restores the prompt. Falls
        back to a direct call when no prompt is running (piped stdin)."""
        loop = self._ptk_loop
        app = getattr(self._ptk_session, "app", None)
        if loop is None or app is None or not getattr(app, "is_running", False):
            return func()
        try:
            from prompt_toolkit.application import run_in_terminal

            # run_in_terminal must be *invoked* inside the prompt_toolkit
            # event loop (it calls get_app()); wrap it in a coroutine so
            # run_coroutine_threadsafe schedules the whole thing there.
            async def _runner() -> Any:
                return await run_in_terminal(func)

            fut = asyncio.run_coroutine_threadsafe(_runner(), loop)
            return fut.result()
        except Exception:  # noqa: BLE001
            return func()

    def _turn_worker(self) -> None:
        """Background turn-runner. Drains the turn queue and runs each
        turn (or a Deep Think pass) serially, so the main thread's input
        line never blocks. Lives for the whole REPL."""
        while not self._worker_stop.is_set():
            try:
                item = self._turn_queue.get(timeout=0.25)
            except queue.Empty:
                self._idle_tick()
                continue
            if item is _WORKER_SHUTDOWN:
                break
            source, text = item
            self._turn_running.set()
            self._turn_started_at = time.perf_counter()
            self._current_activity = "ruminating"
            nxt: str | None = None
            try:
                if source == _DEEPTHINK_SOURCE:
                    self.run_deep_think()
                else:
                    self.run_turn(text, source=source)
                    # Goal loop — evaluate after every real turn; a
                    # not-met goal re-enqueues itself as the next turn.
                    self._current_activity = "evaluating goal"
                    try:
                        nxt = self._post_turn_goal_check()
                    except Exception:  # noqa: BLE001
                        nxt = None
            except Exception as exc:  # noqa: BLE001
                self.console.print(f"[red]turn failed:[/] {exc}")
            finally:
                self._turn_running.clear()
                self._current_activity = ""
            if nxt:
                self._turn_queue.put(("goal", nxt))

    def _idle_tick(self) -> None:
        """Called by the worker whenever the turn queue is empty —
        auto-enters Deep Think once the idle window has elapsed with
        approved work waiting."""
        if self._turn_running.is_set() or self._idle_fired:
            return
        idle = self._auto_idle_seconds()
        if idle <= 0 or time.monotonic() - self._last_activity < idle:
            return
        if not self._turn_queue.empty():
            return
        self._idle_fired = True
        self._turn_running.set()
        self._turn_started_at = time.perf_counter()
        self._current_activity = "deep think"
        try:
            self._maybe_auto_deep_think()
        finally:
            self._turn_running.clear()
            self._current_activity = ""

    def _maybe_auto_deep_think(self) -> None:
        """Idle window elapsed — enter Deep Think if there's approved
        queued work, otherwise quietly keep waiting."""
        try:
            from jaeger_os.core.deep_think import queue_for_layout
            from jaeger_os.core.instance import InstanceLayout
            queue_ = queue_for_layout(InstanceLayout(root=self.instance_dir))
            if queue_.next_pending() is None:
                return  # nothing approved to work — just keep idling
        except Exception:  # noqa: BLE001
            return
        self.console.print(
            "[dim]◎ idle — entering Deep Think to work the queue.[/]"
        )
        self.run_deep_think()

    def _submit_turn(self, source: str, text: str) -> None:
        """Hand a turn to the worker. If a turn is already running, route
        by the busy-input mode (hermes ``/busy``): interrupt the running
        turn, queue after it, or steer it."""
        self._last_activity = time.monotonic()
        self._idle_fired = False
        if not self._turn_running.is_set():
            self._turn_queue.put((source, text))
            return
        mode = self._busy_mode
        if mode == "queue":
            self.console.print(
                "[dim]＋ queued — runs after the current turn.[/]")
            self._turn_queue.put((source, text))
        elif mode == "steer":
            self._submit_steer(text)
        else:  # interrupt (default)
            from jaeger_os.main import request_turn_cancel
            request_turn_cancel()
            self.console.print(
                "[dim]⨯ interrupting — your new message is up next.[/]")
            self._turn_queue.put((source, text))

    def _submit_steer(self, text: str) -> None:
        """Steer the running turn — stop it at the next tool-call
        boundary and continue with this guidance.

        The cancel is checked between agent-loop nodes, so the in-flight
        tool call finishes first (the steer "arrives after the next tool
        call", as in hermes). The partial turn's messages are kept in
        session history, so the steered turn continues with full context
        — the agent absorbs the new direction without losing momentum."""
        from jaeger_os.main import request_turn_cancel
        request_turn_cancel()
        self.console.print(
            "[dim]⤳ steering — finishing the current step, then taking "
            "your guidance.[/]")
        self._turn_queue.put(("text", text))

    def _drain_turn_queue(self) -> None:
        """Discard every queued (not-yet-started) turn — used when the
        user Ctrl-C's to abandon everything pending."""
        try:
            while True:
                self._turn_queue.get_nowait()
        except queue.Empty:
            pass

    def _voice_poll_loop(self) -> None:
        """Background mic poller — runs only while voice is live. Each
        committed phrase becomes a turn, routed through the same
        busy-input rules as a typed line."""
        while not self._voice_stop.is_set():
            v = self._voice
            if v is None or not v.running:
                break
            try:
                phrase = v.poll(timeout=0.25)
            except Exception:  # noqa: BLE001
                phrase = None
            if not phrase:
                continue
            if is_exit_phrase(phrase):
                self.console.print(
                    "[dim]🎙  mic off (spoken stop). /voice on to resume.[/]")
                self._voice_stop.set()
                v.stop()
                self._voice = None
                break
            v.chime("wake")
            self._submit_turn("voice", phrase)

    # ── Busy-input mode ─────────────────────────────────────────────

    def _configured_busy_mode(self) -> str:
        """The busy-input mode from config (``display.busy_input_mode``).
        Defaults to 'interrupt'."""
        try:
            from jaeger_os.main import _pipeline
            cfg = _pipeline.get("config")
            mode = str(getattr(getattr(cfg, "display", None),
                               "busy_input_mode", "interrupt")).lower()
            return mode if mode in ("interrupt", "queue", "steer") \
                else "interrupt"
        except Exception:  # noqa: BLE001
            return "interrupt"

    def set_busy_mode(self, mode: str) -> bool:
        """Set + persist the busy-input mode. Returns False if unknown."""
        mode = (mode or "").strip().lower()
        if mode not in ("interrupt", "queue", "steer"):
            return False
        self._busy_mode = mode
        try:
            from jaeger_os.core.instance import InstanceLayout
            from jaeger_os.core.schemas import dump_yaml
            from jaeger_os.main import _pipeline
            cfg = _pipeline.get("config")
            if cfg is not None:
                cfg.display.busy_input_mode = mode
                dump_yaml(
                    InstanceLayout(root=self.instance_dir).config_path, cfg)
        except Exception:  # noqa: BLE001
            pass
        return True

    # ── Slash dispatch ──────────────────────────────────────────────

    def _dispatch_slash(self, line: str) -> bool:
        """Run a slash command on the main thread. Returns True to quit
        the REPL. Commands that swap the model / instance / pipeline are
        refused while a turn is running."""
        words = line.strip().lstrip("/").split()
        name = words[0].lower() if words else ""
        if name in _TURN_UNSAFE_SLASH and self._turn_running.is_set():
            self.console.print(
                f"[yellow]⏳ a turn is running[/] — Ctrl-C to stop it, or "
                f"wait, before [bold]/{name}[/]."
            )
            return False
        result = dispatch(line, self.slash_ctx)
        if result.message:
            self.console.print(result.message)
        if result.quit:
            return True
        # /deepthink start → run Deep Think on the worker so the input
        # line stays live while it drains the queue.
        if result.extras.get("deep_think_start"):
            self._turn_queue.put((_DEEPTHINK_SOURCE, ""))
        # /goal <condition> fires the first goal turn immediately.
        if result.extras.get("goal_just_set"):
            from jaeger_os.main import get_goal
            active = get_goal()
            if active is not None:
                self._submit_turn("goal", active.condition)
        return False

    # ── REPL ────────────────────────────────────────────────────────

    def repl(self) -> int:
        """Main loop. Returns the exit code.

        The agent turn runs on a background worker thread, so the input
        line is always live — you can type a follow-up, a slash command,
        or (per ``display.busy_input_mode``) interrupt / queue / steer
        while the agent is still working. This is the hermes
        concurrent-input model.

        A goal, when active, drives the next turn from the worker's
        post-turn evaluation. ``deep_think.auto_idle_minutes`` makes the
        worker auto-enter Deep Think after an idle window."""
        self.render_boot()
        # Boot eagerly so the Jaeger is operational the instant the
        # prompt appears.
        self._boot_eager()
        self._print_ready_hint()
        self._busy_mode = self._configured_busy_mode()
        if not sys.stdin.isatty():
            # Piped / non-interactive stdin: no live user to type
            # alongside the agent — run turns synchronously.
            return self._repl_synchronous()
        self._worker = threading.Thread(
            target=self._turn_worker, name="jaeger-turn", daemon=True)
        self._worker.start()
        try:
            while True:
                raw = self._read_line()
                if raw is None:                       # Ctrl-D / EOF
                    self.console.print("\n[dim]bye.[/]")
                    break
                if raw is CTRL_C:                     # Ctrl-C
                    if (self._turn_running.is_set()
                            or not self._turn_queue.empty()):
                        from jaeger_os.main import request_turn_cancel
                        request_turn_cancel()
                        self._drain_turn_queue()
                        self.console.print(
                            "[dim]⨯ interrupted — turn(s) stopped.[/]")
                    else:
                        self.console.print(
                            "[dim](Ctrl-C — nothing running. Ctrl-D or "
                            "/quit to exit.)[/]")
                    continue
                line = str(raw).strip()
                if not line:
                    continue
                if is_slash(line):
                    if self._dispatch_slash(line):
                        break
                    continue
                if _wants_voice_mode(line):
                    # "turn the mic on" typed as text → bring it up.
                    self.start_voice()
                    continue
                self._submit_turn("text", line)
        finally:
            self._shutdown()
        return 0

    def _repl_synchronous(self) -> int:
        """Fallback REPL for piped / non-interactive stdin — read a
        line, run the turn inline, repeat. No worker thread: there is no
        live user typing alongside the agent."""
        pending_goal: str | None = None
        try:
            while True:
                source = "text"
                if pending_goal is not None:
                    line, source, pending_goal = pending_goal, "goal", None
                else:
                    try:
                        raw = input()
                    except (EOFError, KeyboardInterrupt):
                        break
                    line = str(raw).strip()
                    if not line:
                        continue
                    if is_slash(line):
                        result = dispatch(line, self.slash_ctx)
                        if result.message:
                            self.console.print(result.message)
                        if result.quit:
                            break
                        continue
                self.run_turn(line, source=source)
                pending_goal = self._post_turn_goal_check()
        finally:
            self._shutdown()
        return 0

    def _shutdown(self) -> None:
        """Tear down the turn worker, the mic, and the pipeline on REPL
        exit. Idempotent enough to run from the REPL's finally block."""
        # Cancel any in-flight turn so the worker unwinds promptly.
        try:
            from jaeger_os.main import request_turn_cancel
            request_turn_cancel()
        except Exception:  # noqa: BLE001
            pass
        self._worker_stop.set()
        self._turn_queue.put(_WORKER_SHUTDOWN)
        if self._worker is not None:
            self._worker.join(timeout=10.0)
            self._worker = None
        # Mic capture threads come down before the pipeline they feed.
        self.stop_voice()
        # Release the instance lock + shut down extensions before
        # dropping the llama-cpp client (its destructor needs the GIL
        # but not the lock).
        if self._boot is not None:
            try:
                self._boot.cleanup()
            except Exception:  # noqa: BLE001
                pass
        self._agent = None
        self._client = None
        self._boot = None


# ── Entry point ─────────────────────────────────────────────────────


def run(*, skip_model: bool = False) -> int:
    """Public entry: construct + run the Jaeger TUI. Returns exit
    code. ``skip_model=True`` is for banner-only mode."""
    return JaegerTUI(skip_model=skip_model).repl()


if __name__ == "__main__":
    sys.exit(run())
