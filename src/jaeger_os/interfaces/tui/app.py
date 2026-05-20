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

import select
import sys
import time
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.live import Live
from rich.prompt import Prompt
from rich.spinner import Spinner
from rich.text import Text

from jaeger_os import __version__ as JAEGER_VERSION

from .banner import JAEGER_ASCII, TAGLINE
from .slash_commands import SlashContext, dispatch, is_slash
from .status import (
    boot_panel,
    make_session_id,
    status_bar,
)


# Sentinel returned by the timed input path when the idle window
# elapses with no user input — the REPL reads it as "consider
# auto-entering Deep Think".
_IDLE_TIMEOUT = object()


# Resolve default instance dir the same way jaeger.core.prompts does.
_DEFAULT_INSTANCE_DIR = (
    Path(__file__).resolve().parent.parent.parent
    / "instance" / "default"
)


# ── Permission confirmation ──────────────────────────────────────────


class _TuiConfirmationProvider:
    """Confirmation prompt for the TUI.

    A tier-gated tool (run_in_venv, install_package, run_shell, …) asks
    the user for approval through this. It suspends the turn's spinner
    so the prompt is visible, asks via the Rich console, then resumes.
    Answering ``a`` approves and remembers — the rest of the session
    auto-approves so a multi-step build is not a wall of prompts.
    """

    def __init__(self, tui: "JaegerTUI") -> None:
        self._tui = tui
        self._allow_all = False

    def confirm(self, request: Any) -> bool:
        if self._allow_all:
            return True
        live = getattr(self._tui, "_active_live", None)
        if live is not None:
            try:
                live.stop()
            except Exception:
                live = None
        try:
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
                    "  allow?  [bold]y[/]es / [bold]N[/]o / [bold]a[/]llow-all this session: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                console.print()
                return False
            if ans in ("a", "all", "allow-all"):
                self._allow_all = True
                return True
            return ans in ("y", "yes")
        finally:
            if live is not None:
                try:
                    live.start()
                except Exception:
                    pass


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
        self._active_live = None  # the turn's Rich Live, for confirm prompts
        self._started_at = time.perf_counter()
        self._context_tokens = 0
        self._context_max = 8192
        self.slash_ctx = SlashContext(
            console=self.console,
            instance_dir=self.instance_dir,
            tui=self,  # let /instance <name> + /download reach back here
        )

    # ── Boot screen ─────────────────────────────────────────────────

    def render_boot(self) -> None:
        """Print the banner + tagline + boot status panel. One-shot."""
        self.console.print(Text(JAEGER_ASCII, style="bold yellow"))
        self.console.print(Text(TAGLINE, style="dim yellow"))
        self.console.print()
        self.console.print(boot_panel(
            version=self.version,
            instance_name=self.instance_dir.name,
            model_name=self.model_name,
            session_id=self.session_id,
            instance_dir=self.instance_dir,
        ))
        self.console.print()
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
            "[bold yellow]booting jaeger…[/]", spinner="dots",
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
        """Install the TUI-aware permission confirmation provider, so
        tier-gated tools prompt the user (with the spinner suspended)
        instead of being auto-denied. Overrides the generic provider
        ``boot_for_tui`` installs by default."""
        from jaeger_os.core.permissions import PermissionPolicy, install_policy
        install_policy(PermissionPolicy(confirmation=_TuiConfirmationProvider(self)))

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

    # ── Status bar render ───────────────────────────────────────────

    def render_status_bar(
        self, *, state: str = "ready", elapsed_s: float = 0.0,
    ) -> Text:
        uptime = time.perf_counter() - self._started_at
        return status_bar(
            model_name=self.model_name,
            state=state,
            elapsed_s=elapsed_s,
            context_tokens=self._context_tokens,
            context_max=self._context_max,
            uptime_s=uptime,
            voice_state="off",
        )

    # ── Turn ────────────────────────────────────────────────────────

    def run_turn(self, user_text: str) -> None:
        """Run one user turn through jaeger's agent loop.

        Delegates to :func:`jaeger_os.main.run_command` — the same path
        ``python -m jaeger_os`` uses. ``run_command`` prints tool
        activity + answer + latency directly to stdout, so the TUI just
        wraps the call with a ruminating spinner and the status bar."""
        client = self._ensure_agent()
        if client is None:
            self.console.print(
                "[yellow]Agent not initialized (skip_model=True).[/]"
            )
            return

        from jaeger_os.main import run_command

        started = time.perf_counter()
        spinner = Spinner("dots", text="[yellow]ruminating…[/]")
        with Live(
            spinner, console=self.console, refresh_per_second=8,
            transient=True,
        ) as live:
            # Expose the live spinner so a mid-turn permission prompt can
            # suspend it (see _TuiConfirmationProvider).
            self._active_live = live
            try:
                run_command(client, user_text)
            finally:
                self._active_live = None
        elapsed = time.perf_counter() - started

        self.console.print(self.render_status_bar(
            state="ready", elapsed_s=elapsed,
        ))
        self.console.print()

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
        with self.console.status(
            "[dim]◎ evaluating goal…[/]", spinner="dots",
        ):
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
            with self.console.status(
                "[yellow]◎ loading coder model…[/]", spinner="dots",
            ):
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
                with self.console.status(
                    "[yellow]◎ loading realtime model…[/]", spinner="dots",
                ):
                    # switch_model rebuilds the agent, which re-runs the
                    # skill loader — so anything Deep Think authored is
                    # now live for the realtime model.
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

    def _read_line(self) -> Any:
        """Read one line of user input.

        When auto-idle is enabled AND the pipeline is booted, this waits
        only up to the idle window — returning :data:`_IDLE_TIMEOUT` if
        the window elapses with no input, so the REPL can consider
        entering Deep Think. Otherwise it's an ordinary blocking prompt.

        Returns the input string, ``None`` on EOF/interrupt, or
        ``_IDLE_TIMEOUT``."""
        idle = self._auto_idle_seconds()
        if idle <= 0 or self._boot is None:
            try:
                return Prompt.ask("[bold yellow]›[/]")
            except (EOFError, KeyboardInterrupt):
                return None
        # Timed path — print the prompt, then select-wait on stdin.
        self.console.print("[bold yellow]›[/] ", end="")
        try:
            ready, _, _ = select.select([sys.stdin], [], [], idle)
        except (OSError, ValueError):
            # stdin isn't selectable (piped / odd terminal) — fall back.
            try:
                return Prompt.ask("")
            except (EOFError, KeyboardInterrupt):
                return None
        if not ready:
            self.console.print()  # close the prompt line
            return _IDLE_TIMEOUT
        line = sys.stdin.readline()
        if line == "":  # EOF
            return None
        return line.rstrip("\n")

    def _maybe_auto_deep_think(self) -> None:
        """Idle window elapsed — enter Deep Think if there's approved
        queued work, otherwise quietly keep waiting."""
        try:
            from jaeger_os.core.deep_think import queue_for_layout
            from jaeger_os.core.instance import InstanceLayout
            queue = queue_for_layout(InstanceLayout(root=self.instance_dir))
            if queue.next_pending() is None:
                return  # nothing approved to work — just keep idling
        except Exception:  # noqa: BLE001
            return
        self.console.print(
            "[dim]◎ idle — entering Deep Think to work the queue. "
            "(Ctrl-C interrupts.)[/]"
        )
        self.run_deep_think()

    # ── REPL ────────────────────────────────────────────────────────

    def repl(self) -> int:
        """Main loop. Returns the exit code.

        When a goal is active, the next turn's prompt comes from the
        goal loop (the evaluator's "what's still needed" reason) rather
        than from the user — until the condition is met, the iteration
        cap is hit, or the user runs `/goal clear`.

        When ``deep_think.auto_idle_minutes`` is set, an idle window
        with no input auto-enters Deep Think if the queue has approved
        work."""
        self.render_boot()
        pending_goal_prompt: str | None = None
        try:
            while True:
                if pending_goal_prompt is not None:
                    line = pending_goal_prompt
                    pending_goal_prompt = None
                    self.console.print(
                        f"[bold yellow]◎ goal-loop ›[/] [dim]{line[:100]}[/]"
                    )
                else:
                    raw = self._read_line()
                    if raw is _IDLE_TIMEOUT:
                        # No input within the idle window — maybe dream.
                        self._maybe_auto_deep_think()
                        continue
                    if raw is None:
                        self.console.print("\n[dim]bye.[/]")
                        return 0
                    line = str(raw)
                    if not line.strip():
                        continue
                    if is_slash(line):
                        result = dispatch(line, self.slash_ctx)
                        if result.message:
                            self.console.print(result.message)
                        if result.quit:
                            return 0
                        # /deepthink start → enter the Deep Think work
                        # loop (swap to coder model, drain the queue).
                        if result.extras.get("deep_think_start"):
                            self.run_deep_think()
                            continue
                        # /goal <condition> fires the first turn now,
                        # using the condition itself as the prompt.
                        if result.extras.get("goal_just_set"):
                            from jaeger_os.main import get_goal
                            active = get_goal()
                            if active is not None:
                                line = active.condition
                            else:
                                continue
                        else:
                            continue
                self.run_turn(line)
                # After every turn, check the active goal. If it's not
                # met, the returned reason drives the next loop iteration.
                pending_goal_prompt = self._post_turn_goal_check()
        finally:
            # Release the instance lock + shut down extensions before
            # dropping the llama-cpp client (its destructor needs the
            # GIL but not the lock).
            if self._boot is not None:
                try:
                    self._boot.cleanup()
                except Exception:
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
