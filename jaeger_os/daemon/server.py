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
    ends the connection.

    Connection lifecycle is broadcast to the server's optional
    ``on_connect`` / ``on_disconnect`` callbacks so a daemon can keep
    an audit trail of "who's been watching" (DAEMON-E in
    docs/ROADMAP_0.2.0.md).
    """

    # socketserver injects ``server`` for us.
    server: "Server"  # type: ignore[assignment]

    def handle(self) -> None:
        framer = P.Framer()
        sock: socket.socket = self.request
        sock.settimeout(None)  # blocking reads; server lifetime governs

        # Per-connection bookkeeping. The audit hook gets a snapshot
        # at connect time + the live dict at disconnect so it can
        # report ops_called and duration_s.
        client_meta: dict[str, Any] = {
            "client_id": self.server._next_client_id(),
            "started_at": time.time(),
            "ops_called": [],
        }
        self.server._fire_connect(client_meta)

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
                        client_meta["ops_called"].append(msg.op)
                        self._dispatch(msg, sock)
                    # Servers don't take Responses or Events from
                    # clients; ignore them with a debug log.
                    else:  # pragma: no cover
                        self._log("ignoring unexpected %s from client",
                                  type(msg).__name__)
        finally:
            client_meta["ended_at"] = time.time()
            client_meta["duration_s"] = client_meta["ended_at"] - client_meta["started_at"]
            try:
                self.server._fire_disconnect(client_meta)
            except Exception:  # noqa: BLE001 — audit must never crash the handler
                pass
            try:
                sock.close()
            except OSError:
                pass

    def _dispatch(self, req: P.Request, sock: socket.socket) -> None:
        entry = self.server._handlers.get(req.op)
        if entry is None:
            resp = P.Response.for_request(req, error=f"unknown op: {req.op}")
            try:
                sock.sendall(P.encode(resp))
            except (OSError, ConnectionResetError):
                pass
            return

        handler, streaming = entry
        if streaming:
            # Streaming handler — gets an ``emit(name, **payload)``
            # callback that writes Events down the SAME socket. The
            # handler may run for the lifetime of the connection
            # (think ``chat.subscribe``). When it eventually returns,
            # the return value becomes the final Response.
            send_lock = threading.Lock()

            def emit(event_name: str, /, **payload: Any) -> None:
                # ``event_name`` is positional-only so callers can pass
                # ``name`` as a payload key (a frequent shape — e.g.
                # ``tool.progress``'s payload carries the tool name).
                # Lock guards the socket against interleaving with the
                # final Response or with the handler's own emit calls
                # from another thread.
                try:
                    with send_lock:
                        sock.sendall(P.encode(P.Event(name=event_name, payload=payload)))
                except (OSError, ConnectionResetError):
                    # Subscriber vanished. The handler can keep going
                    # if it likes; future emits will also no-op.
                    pass

            try:
                result = handler(emit, **req.params)
                resp = P.Response.for_request(req, ok=True, result=result)
            except Exception as exc:  # noqa: BLE001
                self._log("streaming handler %r raised: %s\n%s",
                          req.op, exc, traceback.format_exc())
                resp = P.Response.for_request(req, error=f"{type(exc).__name__}: {exc}")
            try:
                with send_lock:
                    sock.sendall(P.encode(resp))
            except (OSError, ConnectionResetError):
                return
            return

        # Request-response handler — the common case.
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
                 log: Callable[..., None] | None = None,
                 on_connect: Callable[[dict[str, Any]], None] | None = None,
                 on_disconnect: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.socket_path = Path(socket_path)
        # Each entry is (handler_fn, streaming_flag). Streaming
        # handlers get an ``emit`` callback; request-response ones
        # don't. See ``register`` for the contract.
        self._handlers: dict[str, tuple[HandlerFn, bool]] = {}
        self._server: _ThreadingUnixServer | None = None
        self._thread: threading.Thread | None = None
        self._started_at: float | None = None
        self._log = log or (lambda fmt, *a: None)
        # Connection-lifecycle callbacks — chat_ops wires audit-log
        # writers here. Both are optional; the server has no audit
        # opinions of its own. Guarded by a lock so set_lifecycle_hooks
        # (called after construction by the boot worker) can swap
        # callbacks without racing the accept thread.
        self._lifecycle_lock = threading.Lock()
        self._on_connect = on_connect
        self._on_disconnect = on_disconnect
        # Monotonic counter for client_id assignment.
        self._client_counter = 0
        self._client_counter_lock = threading.Lock()
        self._install_builtin_handlers()

    def set_lifecycle_hooks(
        self,
        *,
        on_connect: Callable[[dict[str, Any]], None] | None = None,
        on_disconnect: Callable[[dict[str, Any]], None] | None = None,
    ) -> None:
        """Swap the connect/disconnect callbacks after the server is
        constructed. Used by the boot worker, which builds the audit
        writer only after ``boot_for_daemon`` has resolved the
        instance layout (the writer needs ``layout.audit_log_path``)."""
        with self._lifecycle_lock:
            if on_connect is not None:
                self._on_connect = on_connect
            if on_disconnect is not None:
                self._on_disconnect = on_disconnect

    def _next_client_id(self) -> int:
        with self._client_counter_lock:
            self._client_counter += 1
            return self._client_counter

    def _fire_connect(self, meta: dict[str, Any]) -> None:
        with self._lifecycle_lock:
            cb = self._on_connect
        if cb is None:
            return
        try:
            cb(meta)
        except Exception:  # noqa: BLE001 — audit must never crash a handler
            pass

    def _fire_disconnect(self, meta: dict[str, Any]) -> None:
        with self._lifecycle_lock:
            cb = self._on_disconnect
        if cb is None:
            return
        try:
            cb(meta)
        except Exception:  # noqa: BLE001
            pass

    # ── handler registry ───────────────────────────────────────────

    def register(self, op: str, fn: HandlerFn, *,
                 replace: bool = False, streaming: bool = False) -> None:
        """Wire an op name to a handler callable.

        ``streaming=False`` (default) — handler signature is
        ``fn(**params) -> JSON-able``; one Request, one Response.

        ``streaming=True`` — handler signature is
        ``fn(emit, **params) -> JSON-able``. ``emit(name, **payload)``
        writes an :class:`Event` down the same socket. The handler may
        run for the lifetime of the connection; its return value
        becomes the final Response after it returns. ``chat.subscribe``
        uses this to push tool-progress / status events as they happen.

        Exceptions are caught and become error responses, never crash
        the server.

        ``replace=False`` (default) raises if the op is already wired,
        which catches accidental re-registration. ``replace=True`` is
        used by the boot worker to swap a "booting" stub for the
        production handler once ``boot_for_daemon`` finishes.
        """
        if not replace and op in self._handlers:
            raise ValueError(f"op {op!r} already registered")
        self._handlers[op] = (fn, streaming)

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
        # Bridge the bound methods the handler needs onto the
        # ``_ThreadingUnixServer`` shim — ``self.server`` inside the
        # handler points to that, not to our ``Server`` wrapper.
        server._next_client_id = self._next_client_id  # type: ignore[attr-defined]
        server._fire_connect = self._fire_connect      # type: ignore[attr-defined]
        server._fire_disconnect = self._fire_disconnect  # type: ignore[attr-defined]
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
