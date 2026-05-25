"""Unix-domain socket server — Phase 1 scaffold.

One ``Server`` instance owns one socket path. ``start()`` binds and spins
an accept loop in a background thread; ``stop()`` shuts down cleanly and
removes the socket file so the next ``start()`` doesn't trip over a
leftover.

Threading model
---------------
``socketserver.ThreadingUnixStreamServer`` spawns one OS thread per
connection. That's fine for Phase 1's tiny set of ops — ping, status,
echo — which all run in microseconds. Phase 2 moves the agent in, and
at that point handler threads will marshal requests onto a single
agent thread (the model isn't thread-safe). We keep the public surface
the same so that change doesn't ripple here.

Handler registry
----------------
Ops are registered via :meth:`Server.register`. The lifecycle layer
(Phase 1.4) wires in the real ops on startup. Three are baked in here
so a fresh server is immediately useful for the tray + tests:

  - ``ping``   → ``{"pong": true}``
  - ``status`` → ``{"running": True, "uptime_s": <float>, "started_at": <ts>}``
  - ``echo``   → returns its params verbatim
"""

from __future__ import annotations

import os
import socket
import socketserver
import threading
import time
import traceback
from pathlib import Path
from typing import Any, Callable

from jaeger_os.daemon import protocol as P


HandlerFn = Callable[..., Any]


# ──────────────────────────────────────────────────────────────────


class _ConnectionHandler(socketserver.BaseRequestHandler):
    """One per accepted connection. Reads NDJSON frames, dispatches
    Requests through the Server's handler registry, writes Responses
    back. A broken frame produces a Response; a broken *socket* just
    ends the connection."""

    # socketserver injects ``server`` for us.
    server: "Server"  # type: ignore[assignment]

    def handle(self) -> None:
        framer = P.Framer()
        sock: socket.socket = self.request
        sock.settimeout(None)  # blocking reads; server lifetime governs
        try:
            while True:
                try:
                    chunk = sock.recv(4096)
                except (OSError, ConnectionResetError):
                    return
                if not chunk:
                    return
                try:
                    framer.feed(chunk)
                except P.ProtocolError as exc:
                    # The frame couldn't be parsed enough to extract an
                    # id, so we can't return a matched Response. Best
                    # we can do is log and drop the connection — the
                    # client will reconnect and retry with valid JSON.
                    self._log("malformed frame: %s", exc)
                    return
                for msg in framer.drain():
                    if isinstance(msg, P.Request):
                        self._dispatch(msg, sock)
                    # Servers don't take Responses or Events from
                    # clients; ignore them with a debug log.
                    else:  # pragma: no cover
                        self._log("ignoring unexpected %s from client",
                                  type(msg).__name__)
        finally:
            try:
                sock.close()
            except OSError:
                pass

    def _dispatch(self, req: P.Request, sock: socket.socket) -> None:
        handler = self.server._handlers.get(req.op)
        if handler is None:
            resp = P.Response.for_request(req, error=f"unknown op: {req.op}")
        else:
            try:
                result = handler(**req.params)
                resp = P.Response.for_request(req, ok=True, result=result)
            except Exception as exc:  # noqa: BLE001 — surface every error
                self._log("handler %r raised: %s\n%s",
                          req.op, exc, traceback.format_exc())
                resp = P.Response.for_request(req, error=f"{type(exc).__name__}: {exc}")
        try:
            sock.sendall(P.encode(resp))
        except (OSError, ConnectionResetError):
            # Client vanished mid-response. Nothing useful to do here.
            return

    def _log(self, fmt: str, *args: Any) -> None:
        # Routed through the server's logger so tests can swap it.
        self.server._log(fmt, *args)


class _ThreadingUnixServer(socketserver.ThreadingUnixStreamServer):
    """Tiny shim so daemon threads die with the parent process."""
    allow_reuse_address = True
    daemon_threads = True


# ──────────────────────────────────────────────────────────────────


class Server:
    """The public surface — a daemon-side socket listener.

    Construct with the path to bind, call ``start()`` to begin accepting
    connections in a background thread, ``stop()`` to tear everything
    down. Safe to call ``stop()`` multiple times.
    """

    def __init__(self, *, socket_path: Path | str,
                 log: Callable[..., None] | None = None) -> None:
        self.socket_path = Path(socket_path)
        self._handlers: dict[str, HandlerFn] = {}
        self._server: _ThreadingUnixServer | None = None
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._log = log or (lambda fmt, *a: None)
        self._install_builtin_handlers()

    # ── handler registry ───────────────────────────────────────────

    def register(self, op: str, fn: HandlerFn) -> None:
        """Wire an op name to a handler callable.

        The handler is called with the Request's ``params`` as kwargs and
        must return a JSON-serializable value (or raise — exceptions
        become error responses, never crash the server)."""
        if op in self._handlers:
            raise ValueError(f"op {op!r} already registered")
        self._handlers[op] = fn

    def _install_builtin_handlers(self) -> None:
        self.register("ping", lambda **kw: {"pong": True})
        self.register("status", self._status)
        self.register("echo", lambda **kw: dict(kw))

    def _status(self, **_: Any) -> dict[str, Any]:
        return {
            "running": True,
            "uptime_s": (time.monotonic() - self._started_at) if self._started_at else 0.0,
            "started_at": self._started_at,
            # Phase 2 adds: attached_clients, current_phase, model_loaded
        }

    # ── lifecycle ──────────────────────────────────────────────────

    def start(self) -> None:
        """Bind the socket and start accepting in a background thread."""
        if self._server is not None:
            raise RuntimeError("server already started")
        # Prevent leftover-from-crash sockets from blocking the bind.
        if self.socket_path.exists():
            self.socket_path.unlink()
        self.socket_path.parent.mkdir(parents=True, exist_ok=True)

        server = _ThreadingUnixServer(str(self.socket_path), _ConnectionHandler)
        server._handlers = self._handlers  # type: ignore[attr-defined]
        server._log = self._log            # type: ignore[attr-defined]
        # Tighten the socket file's permissions — Unix sockets respect
        # filesystem ACLs, and we want only this user reading/writing.
        os.chmod(self.socket_path, 0o600)

        self._server = server
        self._started_at = time.monotonic()
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="jaeger-daemon-accept",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        """Shut down the accept loop, close the socket, unlink the file."""
        if self._server is None:
            return
        try:
            self._server.shutdown()
            self._server.server_close()
        except Exception:  # noqa: BLE001 — stop() must be best-effort
            pass
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        try:
            if self.socket_path.exists():
                self.socket_path.unlink()
        except OSError:
            pass
        self._server = None
        self._thread = None
        self._started_at = None


__all__ = ["Server"]
