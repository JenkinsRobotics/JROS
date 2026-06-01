"""Daemon socket client — connect, send Request, await Response.

A small synchronous client suitable for the CLI (`jaeger status` /
`jaeger attach`'s initial handshake) and for the tray icon's polling.
The TUI client in Phase 2 layers a richer event loop on top of this
same connection; the basics live here so both paths share the same
wire-level code.

Usage::

    with Client(socket_path=path) as c:
        resp = c.call("ping")
        assert resp.ok

The client is **not thread-safe** — one connection, one caller. A
multi-threaded UI should keep one client per thread or wrap calls in
its own lock.
"""

from __future__ import annotations

import itertools
import socket
from pathlib import Path
from typing import Any

from jaeger_os.daemon import protocol as P


class DaemonNotRunning(RuntimeError):
    """The socket file is missing or refusing connections.

    Surfaced as a distinct type so the CLI can render "Daemon not
    running — start it with ``jaeger start``" instead of an opaque
    ``ConnectionRefusedError`` from deep in the socket layer."""


class Client:
    """One TCP-style request/response conversation over the daemon
    socket. Lifecycle is owned by the caller (or by ``with`` block)."""

    def __init__(self, *, socket_path: Path | str,
                 connect_timeout: float = 2.0,
                 call_timeout: float = 10.0) -> None:
        self.socket_path = Path(socket_path)
        self._connect_timeout = connect_timeout
        self._call_timeout = call_timeout
        self._sock: socket.socket | None = None
        self._framer = P.Framer()
        # Caller doesn't need to manage request ids; we autogenerate.
        self._next_id = itertools.count(1)

    # ── context manager sugar ──────────────────────────────────────

    def __enter__(self) -> "Client":
        self._connect()
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    # ── primary API ────────────────────────────────────────────────

    def call(self, op: str, **params: Any) -> P.Response:
        """Send a Request and block until the matching Response arrives.

        Phase 1: every call is sequential on the connection, so the
        ``id`` round-trip is more about future-proofing than today's
        ordering — but we honour it anyway so a Phase 2 streaming
        client (which interleaves events with responses) can use the
        same code path."""
        if self._sock is None:
            self._connect()
        assert self._sock is not None
        req = P.Request(id=next(self._next_id), op=op, params=params)
        try:
            self._sock.sendall(P.encode(req))
        except (BrokenPipeError, ConnectionResetError) as exc:
            raise DaemonNotRunning(
                f"connection to {self.socket_path} closed mid-send: {exc}"
            ) from exc

        # Drain frames until we see the matched Response. Events that
        # may arrive in the meantime are dropped on the floor — Phase 1
        # callers don't subscribe to them. Phase 2 will route events
        # to a callback before this loop pulls the response.
        deadline_sock = self._sock
        deadline_sock.settimeout(self._call_timeout)
        while True:
            try:
                chunk = deadline_sock.recv(4096)
            except socket.timeout as exc:
                raise TimeoutError(
                    f"daemon did not answer {op!r} within "
                    f"{self._call_timeout}s"
                ) from exc
            if not chunk:
                raise DaemonNotRunning(
                    f"daemon at {self.socket_path} closed the connection"
                )
            try:
                self._framer.feed(chunk)
            except P.ProtocolError as exc:
                # The server sent us garbage. That's a server bug, not
                # something the caller can recover from — surface it.
                raise RuntimeError(f"daemon protocol error: {exc}") from exc
            for msg in self._framer.drain():
                if isinstance(msg, P.Response) and msg.id == req.id:
                    return msg
                # Drop everything else (Events, mismatched-id Responses).

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None

    # ── internals ──────────────────────────────────────────────────

    def _connect(self) -> None:
        if not self.socket_path.exists():
            raise DaemonNotRunning(
                f"no socket at {self.socket_path} — is the daemon running?"
            )
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self._connect_timeout)
        try:
            sock.connect(str(self.socket_path))
        except (ConnectionRefusedError, FileNotFoundError) as exc:
            sock.close()
            raise DaemonNotRunning(
                f"daemon at {self.socket_path} refused connection: {exc}"
            ) from exc
        except OSError as exc:
            sock.close()
            raise DaemonNotRunning(
                f"could not connect to {self.socket_path}: {exc}"
            ) from exc
        self._sock = sock


__all__ = ["Client", "DaemonNotRunning"]
