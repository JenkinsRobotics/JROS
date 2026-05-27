"""Rich-TUI app — daemon-attached REPL.

Same scrollback-shaped chrome as ``jaeger tui`` (banner + boot panel +
turn rules + answer box + status bar), but the agent doesn't live in
this process. Each turn becomes:

  1. user types a line → we send ``chat.send`` to the daemon
  2. a background subscriber prints ``tool.progress`` / ``turn.*``
     events from ``chat.subscribe`` as they arrive
  3. ``chat.send`` returns with the final answer text → we render it

Reuses the existing TUI's banner / theme / ptk_input / completion
modules by **import**, not duplication — we don't touch
``interfaces/tui/`` at all (per the project's "preserve 0.1.0
surfaces" rule).
"""

from __future__ import annotations

import socket as _socket
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from prompt_toolkit.formatted_text import ANSI
from rich.console import Console
from rich.panel import Panel
from rich.padding import Padding
from rich.rule import Rule
from rich.text import Text

from jaeger_os import __version__ as JAEGER_VERSION
from jaeger_os.daemon import protocol as P
from jaeger_os.daemon.client import Client, DaemonNotRunning

# Reused FROM the existing TUI — by import, not modification.
from jaeger_os.interfaces.tui.banner import JAEGER_ASCII, TAGLINE
from jaeger_os.interfaces.tui.ptk_input import CTRL_C, build_session, read_prompt
from jaeger_os.interfaces.tui.theme import ACCENT, ACCENT_BOLD, ACCENT_DIM, ACCENT_PTK


# ── handful of slash commands ──────────────────────────────────────


_HELP_LINES = [
    ("/help", "show this help"),
    ("/status", "print the daemon's current snapshot"),
    ("/history [N]", "show the last N (default 20) messages"),
    ("/clear", "clear the screen"),
    ("/quit", "exit (daemon keeps running)"),
]


# ── connection wrapper ─────────────────────────────────────────────


@dataclass
class DaemonHandle:
    """Bundle of two open connections to the same daemon socket — one
    long-lived subscriber, one short-lived sender. Splitting them keeps
    a hung ``chat.send`` from blocking the event stream and vice versa."""

    sock_path: Path
    subscriber_sock: _socket.socket | None = None
    subscriber_thread: threading.Thread | None = None
    closed: bool = False


def _probe_daemon(sock_path: Path, console: Console) -> dict[str, Any] | None:
    """Single quick call: ``status.snapshot`` so we can print the boot
    panel with real numbers AND fail fast if the daemon's down. Returns
    the snapshot dict on success, ``None`` on failure (already logged)."""
    if not sock_path.exists():
        console.print(
            f"[red]daemon not running[/red] — no socket at {sock_path}.\n"
            f"Start it with [bold]jaeger start[/bold] first, "
            f"then re-run [bold]jaeger rich-tui[/bold].",
        )
        return None
    try:
        with Client(socket_path=sock_path) as c:
            resp = c.call("status.snapshot")
    except DaemonNotRunning as exc:
        console.print(f"[red]daemon unreachable:[/red] {exc}")
        return None
    if not resp.ok:
        console.print(f"[red]status.snapshot failed:[/red] {resp.error}")
        return None
    return dict(resp.result or {})


# ── boot chrome ────────────────────────────────────────────────────


def _render_banner(console: Console) -> None:
    txt = Text(JAEGER_ASCII, style=ACCENT_BOLD)
    console.print(Padding(txt, (1, 0, 0, 0)))
    console.print(Padding(Text(TAGLINE, style=ACCENT_DIM, justify="center"),
                          (0, 0, 1, 0)))


def _render_boot_panel(console: Console, snap: dict[str, Any], sock_path: Path) -> None:
    """One-line-per-fact boot panel — pulls everything from the
    daemon's status.snapshot so we don't have to re-resolve config."""
    model_path = snap.get("model_path") or "(unknown)"
    instance = snap.get("instance") or "(unknown)"
    ctx = snap.get("ctx")
    uptime = snap.get("uptime_s") or 0.0
    agent_ready = snap.get("agent_ready", True)  # absent on full snapshot
    turns = snap.get("turns_completed", 0)

    body = Text()
    body.append("daemon  ", style=ACCENT_DIM)
    body.append(str(sock_path), style="white")
    body.append("\n")
    body.append("instance  ", style=ACCENT_DIM)
    body.append(str(instance), style="white")
    body.append("\n")
    body.append("model     ", style=ACCENT_DIM)
    body.append(Path(model_path).name if model_path else "?", style="white")
    if isinstance(ctx, int):
        body.append(f"   ctx={ctx}", style="dim")
    body.append("\n")
    body.append("uptime    ", style=ACCENT_DIM)
    body.append(f"{uptime:.1f}s", style="white")
    body.append(f"   turns={turns}", style="dim")
    if not agent_ready:
        body.append("\n")
        body.append("status    ", style=ACCENT_DIM)
        body.append("agent still booting", style="yellow")

    console.print(Panel(body, title="[bold]jaeger rich-tui[/bold]  "
                                    f"[dim]v{JAEGER_VERSION}[/dim]",
                        border_style=ACCENT, padding=(0, 1)))


# ── event subscriber ───────────────────────────────────────────────


def _start_subscriber(sock_path: Path, console: Console,
                      stop: threading.Event,
                      sock_holder: dict[str, Any]) -> threading.Thread:
    """Spawn a daemon thread that opens its own connection, calls
    ``chat.subscribe``, and renders incoming events through the same
    ``console`` the main thread uses. Returns the Thread so the
    caller can join it on shutdown."""

    def _print_event(evt: P.Event) -> None:
        name = evt.name
        payload = evt.payload
        if name == "subscribed":
            return  # quiet — boot panel already showed the connection
        if name == "tool.progress":
            tool = payload.get("name", "?")
            phase = payload.get("phase", "?")
            elapsed = payload.get("elapsed_s")
            tail = f" ({elapsed:.2f}s)" if isinstance(elapsed, (int, float)) else ""
            console.print(f"  [{ACCENT_DIM}]▸[/] [dim]{tool} {phase}{tail}[/dim]")
            return
        if name == "turn.start":
            # The main thread prints the user's input as a ruled
            # header; turn.start would be redundant. Show nothing
            # here so the stream stays uncluttered.
            return
        if name == "turn.complete":
            return  # the main thread will render the answer when chat.send returns
        # Unknown event — surface generically for forward-compat.
        console.print(f"  [{ACCENT_DIM}]·[/] [dim]{name} {payload}[/dim]")

    def _run() -> None:
        sock = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
        sock.settimeout(2.0)
        try:
            sock.connect(str(sock_path))
        except OSError as exc:
            console.print(f"  [red][subscriber] connect failed:[/red] {exc}")
            return
        sock_holder["sock"] = sock
        try:
            sock.sendall(P.encode(P.Request(id=1, op="chat.subscribe")))
            sock.settimeout(None)
        except OSError:
            return
        framer = P.Framer()
        try:
            while not stop.is_set():
                try:
                    chunk = sock.recv(4096)
                except OSError:
                    return
                if not chunk:
                    return
                framer.feed(chunk)
                for msg in framer.drain():
                    if isinstance(msg, P.Event):
                        _print_event(msg)
                    elif isinstance(msg, P.Response) and not msg.ok:
                        console.print(f"  [red][subscriber] error:[/red] {msg.error}")
                        return
        finally:
            try:
                sock.close()
            except OSError:
                pass

    t = threading.Thread(target=_run, name="rich-tui-subscriber", daemon=True)
    t.start()
    return t


def _stop_subscriber(thread: threading.Thread | None,
                     sock_holder: dict[str, Any],
                     stop: threading.Event) -> None:
    stop.set()
    sock = sock_holder.get("sock")
    if sock is not None:
        try:
            sock.shutdown(_socket.SHUT_RDWR)
        except OSError:
            pass
        try:
            sock.close()
        except OSError:
            pass
    if thread is not None:
        thread.join(timeout=1.0)


# ── slash commands (in-process, tiny set) ──────────────────────────


def _do_slash(text: str, *, sock_path: Path, console: Console,
              session_key: str) -> bool:
    """Return True if the input was a slash command (handled here);
    False if it should be forwarded to the agent as a normal message.

    Only a handful of commands today — anything that needs the agent
    routes through ``chat.send``. The 0.1.0 TUI has a much fuller
    slash command set; we're not duplicating it. Users who want it
    can run ``jaeger tui`` (the in-process surface)."""
    if not text.startswith("/"):
        return False
    parts = text.split(maxsplit=1)
    cmd = parts[0]
    arg = parts[1] if len(parts) > 1 else ""

    if cmd in ("/quit", "/exit", "/q"):
        raise _Quit()

    if cmd in ("/help", "/?"):
        body = Text()
        for verb, blurb in _HELP_LINES:
            body.append(f"  {verb:<18}", style=ACCENT_BOLD)
            body.append(blurb + "\n")
        body.append("\n  ")
        body.append("Anything else is sent to the agent as a message.",
                    style="dim")
        console.print(Panel(body, title="rich-tui commands",
                            border_style=ACCENT_DIM, padding=(0, 1)))
        return True

    if cmd == "/clear":
        console.clear()
        return True

    if cmd == "/status":
        snap = _probe_daemon(sock_path, console)
        if snap is not None:
            _render_boot_panel(console, snap, sock_path)
        return True

    if cmd == "/history":
        try:
            limit = int(arg) if arg else 20
        except ValueError:
            console.print(f"  [yellow]/history expects an integer; got {arg!r}[/yellow]")
            return True
        try:
            with Client(socket_path=sock_path) as c:
                resp = c.call("chat.history", session_key=session_key, limit=limit)
        except DaemonNotRunning as exc:
            console.print(f"  [red]/history: {exc}[/red]")
            return True
        if not resp.ok:
            console.print(f"  [red]/history failed:[/red] {resp.error}")
            return True
        msgs = resp.result.get("messages", [])
        if not msgs:
            console.print("  [dim](no messages yet — say hi to the agent first)[/dim]")
            return True
        body = Text()
        for m in msgs:
            role = m.get("role", "?")
            content = m.get("content", "")
            if isinstance(content, list):
                content = " ".join(str(c) for c in content if c)
            body.append(f"{role}: ", style=ACCENT_DIM)
            body.append(str(content)[:200] + "\n")
        console.print(Panel(body, title=f"last {len(msgs)} message(s)",
                            border_style=ACCENT_DIM, padding=(0, 1)))
        return True

    console.print(f"  [yellow]unknown command:[/yellow] {cmd}   "
                  "(type /help)")
    return True


class _Quit(Exception):
    """Raised by a slash command to unwind the REPL cleanly."""


# ── main loop ──────────────────────────────────────────────────────


def _format_status_bar(state: dict[str, Any]) -> ANSI:
    """One-line status above the input prompt. ``state`` is a dict
    the main loop mutates ('idle' / 'sending' / 'thinking' / 'error')
    so the bar reflects what's actually happening."""
    phase = state.get("phase", "idle")
    detail = state.get("detail", "")
    if phase == "thinking":
        spin = "◐◓◑◒"[int(time.monotonic() * 6) % 4]
        bar = f"\x1b[38;2;58;160;255m  {spin}\x1b[0m \x1b[2mthinking…{(' ' + detail) if detail else ''}\x1b[0m"
    elif phase == "sending":
        bar = "\x1b[38;2;58;160;255m  ●\x1b[0m \x1b[2msending…\x1b[0m"
    elif phase == "error":
        bar = f"\x1b[31m  ✗ {detail}\x1b[0m"
    else:
        bar = "\x1b[2m  ready · /help for commands · /quit to exit\x1b[0m"
    return ANSI(bar + "\n")


def _format_prompt() -> ANSI:
    return ANSI(f"\x1b[38;2;58;160;255m❯\x1b[0m ")


def _render_turn_header(console: Console, text: str) -> None:
    """The hermes-style ── / ● <user text> rule above the agent's
    response. Mirrors the existing TUI's shape so users don't have to
    relearn the visual rhythm."""
    console.print()
    console.print(Rule(style=ACCENT_DIM))
    bullet = Text("●  ", style=ACCENT_BOLD)
    body = Text(text, style="white")
    console.print(bullet + body)


def _render_answer(console: Console, text: str, elapsed_s: float | None) -> None:
    if not text:
        return
    answer = Text(text, style="white")
    panel = Panel(answer, border_style=ACCENT_DIM, padding=(0, 1))
    console.print(panel)
    if elapsed_s is not None:
        console.print(Text(f"  ({elapsed_s:.2f}s)", style="dim"))


def run(*, sock_path: Path, session_key: str = "rich-tui") -> int:
    """Run one rich-tui session against the daemon at ``sock_path``.
    Returns the exit code the CLI should hand back."""
    console = Console()

    _render_banner(console)
    snap = _probe_daemon(sock_path, console)
    if snap is None:
        return 1
    _render_boot_panel(console, snap, sock_path)

    state: dict[str, Any] = {"phase": "idle", "detail": ""}
    stop_events = threading.Event()
    sub_holder: dict[str, Any] = {}
    sub_thread = _start_subscriber(sock_path, console, stop_events, sub_holder)

    session = build_session()
    try:
        while True:
            text = read_prompt(
                session,
                message=lambda: _format_status_bar(state) + _format_prompt(),
            )
            if text is None:
                # Ctrl-D / EOF — quit cleanly.
                console.print("\n[dim]bye — daemon keeps running.[/dim]")
                break
            if text is CTRL_C:
                console.print("[dim](Ctrl-C ignored — use /quit or Ctrl-D to exit)[/dim]")
                continue
            text = str(text).strip()
            if not text:
                continue

            # Slash commands handled locally; everything else → daemon.
            try:
                if _do_slash(text, sock_path=sock_path,
                             console=console, session_key=session_key):
                    continue
            except _Quit:
                console.print("[dim]bye — daemon keeps running.[/dim]")
                break

            _render_turn_header(console, text)
            state["phase"] = "thinking"
            state["detail"] = ""
            try:
                with Client(socket_path=sock_path, call_timeout=600.0) as c:
                    resp = c.call("chat.send", text=text, session_key=session_key)
            except DaemonNotRunning as exc:
                state["phase"] = "error"
                state["detail"] = "daemon dropped"
                console.print(f"  [red]daemon dropped:[/red] {exc}")
                break
            except TimeoutError:
                state["phase"] = "error"
                state["detail"] = "turn timed out"
                console.print("  [red]turn timed out (10 min).[/red]")
                continue

            if not resp.ok:
                state["phase"] = "error"
                state["detail"] = resp.error or "?"
                console.print(f"  [red]error:[/red] {resp.error}")
                continue

            result = resp.result or {}
            err = result.get("error")
            if err:
                state["phase"] = "error"
                state["detail"] = err[:40]
                console.print(f"  [red]turn error:[/red] {err}")
                continue

            state["phase"] = "idle"
            state["detail"] = ""
            _render_answer(console, result.get("text") or "",
                           result.get("elapsed_s"))
    finally:
        _stop_subscriber(sub_thread, sub_holder, stop_events)
    return 0
