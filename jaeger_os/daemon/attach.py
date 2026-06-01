"""``jaeger attach`` — a headless streaming client.

Connects to the running daemon, opens a ``chat.subscribe`` stream on
one connection (to watch tool activity in real time), reads user
input from stdin, and posts each line via ``chat.send`` on a second
connection. Quit with EOF / Ctrl-D / Ctrl-C; the daemon keeps
running.

Two connections (not one) because ``chat.subscribe`` is a *streaming*
handler — it owns its socket until the client disconnects. ``chat.send``
is request-response and needs its own connection to round-trip.

Output shape — text only, no curses / ANSI. Intended for piping into
a logger, ``tee``, or another process:

    > hi there
    [tool] tool.progress name=echo phase=start
    [tool] tool.progress name=echo phase=done elapsed_s=0.001
    Hi back!  (0.42s)
"""

from __future__ import annotations

import argparse
import socket as _socket
import sys
import threading
import time
from pathlib import Path
from typing import Any

from jaeger_os.daemon import protocol as P
from jaeger_os.daemon.client import Client, DaemonNotRunning


def _print_attach_usage() -> None:
    print(
        "usage: jaeger attach [--instance NAME] [--session KEY] [--no-events]\n"
        "\n"
        "  Connects to the running daemon and chats with the agent.\n"
        "  Type a line and press Enter to send; Ctrl-D / Ctrl-C exits.\n"
        "  The daemon keeps running after you quit.\n"
        "\n"
        "options:\n"
        "  --instance NAME    instance name (default: JAEGER_INSTANCE_NAME or 'default')\n"
        "  --session KEY      session key for chat.send (default: 'attach')\n"
        "  --no-events        skip the chat.subscribe stream (just send/receive)\n",
        file=sys.stderr,
    )


def _cmd_attach_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger attach", add_help=False)
    parser.add_argument("--instance", default=None)
    parser.add_argument("--session", default="attach")
    parser.add_argument("--no-events", dest="events", action="store_false", default=True)
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        _print_attach_usage()
        return 0

    from jaeger_os.core.instance.instance import (
        default_instance_name, resolve_instance_dir,
    )
    name = args.instance or default_instance_name()
    root = Path(resolve_instance_dir(name))
    sock_path = root / "run" / "jaeger.sock"
    return run_attach(
        sock_path=sock_path,
        session_key=args.session,
        subscribe_events=args.events,
        stdin=sys.stdin,
        stdout=sys.stdout,
        stderr=sys.stderr,
    )


def run_attach(*, sock_path: Path,
               session_key: str = "attach",
               subscribe_events: bool = True,
               stdin: Any = None,
               stdout: Any = None,
               stderr: Any = None) -> int:
    """Drive an attach session against the daemon at ``sock_path``.

    Split from ``_cmd_attach_argv`` so tests can inject fake
    stdin / stdout / stderr without going through argparse + the
    instance resolver.
    """
    stdin = stdin if stdin is not None else sys.stdin
    stdout = stdout if stdout is not None else sys.stdout
    stderr = stderr if stderr is not None else sys.stderr

    if not sock_path.exists():
        print(f"daemon not running (no socket at {sock_path}). "
              "Start it with `jaeger start`.", file=stderr)
        return 1

    # Probe with a quick ping so we fail fast if the socket is dead.
    try:
        with Client(socket_path=sock_path) as c:
            resp = c.call("ping")
            if not resp.ok:
                print(f"daemon ping failed: {resp.error}", file=stderr)
                return 1
    except DaemonNotRunning as exc:
        print(f"daemon unreachable: {exc}", file=stderr)
        return 1

    # Event subscriber thread — connects, calls chat.subscribe, prints
    # each Event as it arrives. Runs until the daemon closes the
    # socket or the main thread sets ``stop_events``.
    stop_events = threading.Event()
    subscriber_thread: threading.Thread | None = None
    sub_sock_holder: dict[str, Any] = {"sock": None}

    if subscribe_events:
        def _subscriber() -> None:
            sub = _socket.socket(_socket.AF_UNIX, _socket.SOCK_STREAM)
            sub.settimeout(2.0)
            try:
                sub.connect(str(sock_path))
            except OSError as exc:
                print(f"[attach] subscribe failed: {exc}", file=stderr)
                return
            sub_sock_holder["sock"] = sub
            sub.sendall(P.encode(P.Request(id=1, op="chat.subscribe")))
            sub.settimeout(None)  # block forever between events
            framer = P.Framer()
            try:
                while not stop_events.is_set():
                    try:
                        chunk = sub.recv(4096)
                    except OSError:
                        return
                    if not chunk:
                        return
                    framer.feed(chunk)
                    for msg in framer.drain():
                        if isinstance(msg, P.Event):
                            _print_event(msg, stdout)
                        elif isinstance(msg, P.Response) and not msg.ok:
                            print(f"[attach] subscribe error: {msg.error}",
                                  file=stderr)
                            return
            finally:
                try:
                    sub.close()
                except OSError:
                    pass

        subscriber_thread = threading.Thread(
            target=_subscriber, name="attach-subscriber", daemon=True,
        )
        subscriber_thread.start()
        # Tiny wait so the "subscribed" event lands before the user
        # starts typing — purely cosmetic.
        time.sleep(0.05)

    print(f"[attach] connected to {sock_path} — type your message, "
          f"Ctrl-D to quit.", file=stderr)

    # Sender loop — one chat.send per line of input. We open a fresh
    # Client each turn so a hung send can't poison the next; the
    # daemon doesn't care which connection a request comes in on.
    try:
        while True:
            try:
                line = stdin.readline()
            except KeyboardInterrupt:
                print("", file=stdout)
                break
            if not line:
                break  # EOF
            text = line.rstrip("\n")
            if not text:
                continue
            try:
                with Client(socket_path=sock_path, call_timeout=600.0) as c:
                    resp = c.call("chat.send", text=text, session_key=session_key)
            except DaemonNotRunning as exc:
                print(f"[attach] daemon dropped: {exc}", file=stderr)
                return 2
            except TimeoutError:
                print("[attach] daemon did not answer within 10 minutes.",
                      file=stderr)
                continue
            _print_response(resp, stdout, stderr)
    finally:
        # Give the subscriber a short window to drain whatever events
        # are still in flight from the last turn (turn.complete +
        # late tool.progress frames). Without this the test — and the
        # user's terminal — loses the tail of the stream every time
        # the input pipe closes immediately after a send.
        if subscriber_thread is not None:
            time.sleep(0.1)
        stop_events.set()
        # Closing the subscriber's socket from this thread is the only
        # reliable way to unblock its ``recv`` (settimeout(None) above
        # makes the recv un-cancellable otherwise).
        sub_sock = sub_sock_holder.get("sock")
        if sub_sock is not None:
            try:
                sub_sock.shutdown(_socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                sub_sock.close()
            except OSError:
                pass
        if subscriber_thread is not None:
            subscriber_thread.join(timeout=1.0)
    return 0


# ── output helpers ─────────────────────────────────────────────────


def _print_event(evt: P.Event, stdout: Any) -> None:
    name = evt.name
    payload = evt.payload
    if name == "subscribed":
        # Mostly internal — show once at the start so the user knows
        # the stream is live.
        print(f"[attach] event stream live (subscription_id="
              f"{payload.get('subscription_id')}).", file=stdout)
        return
    if name == "tool.progress":
        tool = payload.get("name", "?")
        phase = payload.get("phase", "?")
        elapsed = payload.get("elapsed_s")
        elapsed_str = f" ({elapsed:.3f}s)" if isinstance(elapsed, (int, float)) else ""
        print(f"  ▸ {tool} {phase}{elapsed_str}", file=stdout)
        return
    if name == "turn.start":
        print(f"  · thinking…", file=stdout)
        return
    if name == "turn.complete":
        # The full answer is also returned from chat.send's Response,
        # which the sender prints. We could double-print it here; we
        # don't, to keep the stream short.
        return
    # Unknown event — render generically so future verbs surface in
    # the stream without a code change.
    print(f"  · {name} {payload}", file=stdout)


def _print_response(resp: P.Response, stdout: Any, stderr: Any) -> None:
    if not resp.ok:
        print(f"[attach] error: {resp.error}", file=stderr)
        return
    result = resp.result or {}
    err = result.get("error")
    if err:
        print(f"[attach] turn error: {err}", file=stderr)
        return
    text = result.get("text") or ""
    elapsed = result.get("elapsed_s")
    if text:
        print(text, file=stdout)
    if isinstance(elapsed, (int, float)):
        print(f"  ({elapsed:.2f}s)", file=stdout)


__all__ = ["run_attach", "_cmd_attach_argv"]
