"""Server + client over a Unix-domain socket — the smallest end-to-end
test that exercises the wire protocol against real socket IO.

We run the server in a background thread, point the client at the same
``.sock`` path on disk, and assert on the messages that come back. No
fork, no PID file — those are the next phase. Here we're checking:

  - the server binds the socket, accepts connections, dispatches ops
  - the client encodes a Request and decodes the matching Response
  - an unknown op returns an error response, not a crashed connection
  - garbage bytes don't take the server down
  - the server shuts down cleanly and removes the socket file
"""

from __future__ import annotations

import socket
import tempfile
import threading
import time
from pathlib import Path

import pytest

from jaeger_os.daemon import protocol as P
from jaeger_os.daemon.client import Client
from jaeger_os.daemon.server import Server


@pytest.fixture
def short_tmp():
    """Unix-domain socket paths are capped at 104 bytes on macOS / 108 on
    Linux. pytest's default ``tmp_path`` blows past that, so tests that
    need a real socket use this short-prefix fixture instead."""
    d = Path(tempfile.mkdtemp(prefix="jd-", dir="/tmp"))
    try:
        yield d
    finally:
        # Best-effort cleanup; leftover sockets are inert.
        for p in d.iterdir():
            try:
                p.unlink()
            except OSError:
                pass
        try:
            d.rmdir()
        except OSError:
            pass


@pytest.fixture
def server_and_client(short_tmp):
    """Stand up a server on a tmp socket; yield (server, client_factory).
    Tests use ``client_factory()`` to get a fresh ``Client`` (so a
    test that asserts on connect-state doesn't poison the next test)."""
    sock_path = short_tmp / "jaeger.sock"
    server = Server(socket_path=sock_path)
    server.start()
    # The server starts its accept loop in a thread; give it a beat to
    # bind before the client connects. A tighter sync would be nicer,
    # but a small sleep is robust on every platform.
    for _ in range(50):
        if sock_path.exists():
            break
        time.sleep(0.01)
    assert sock_path.exists(), "server failed to bind its socket"
    try:
        yield server, (lambda: Client(socket_path=sock_path))
    finally:
        server.stop()


# ── ping: the smallest possible round-trip ─────────────────────────


def test_ping_returns_pong(server_and_client):
    server, make_client = server_and_client
    with make_client() as c:
        resp = c.call("ping")
    assert resp.ok is True
    assert resp.result == {"pong": True}


def test_status_returns_running_state(server_and_client):
    """``status`` is the op the tray icon polls — it must always return
    *something* fast (no blocking on agent state, no model lookups)."""
    server, make_client = server_and_client
    with make_client() as c:
        resp = c.call("status")
    assert resp.ok is True
    assert resp.result["running"] is True
    # uptime is monotonically increasing while the server is up.
    assert resp.result["uptime_s"] >= 0


def test_echo_reflects_params(server_and_client):
    """``echo`` is a debugging op — it just hands back its params.
    Useful for confirming the params field made the round trip."""
    server, make_client = server_and_client
    with make_client() as c:
        resp = c.call("echo", text="hello", n=3)
    assert resp.ok is True
    assert resp.result == {"text": "hello", "n": 3}


# ── error cases ────────────────────────────────────────────────────


def test_unknown_op_returns_error_response_not_disconnect(server_and_client):
    """A typo'd op gets a structured error — the connection stays open
    so the client can retry with the right name."""
    server, make_client = server_and_client
    with make_client() as c:
        resp = c.call("nonexistent_op")
        assert resp.ok is False
        assert "unknown op" in (resp.error or "").lower()
        # Connection still alive — a follow-up ping works.
        resp2 = c.call("ping")
        assert resp2.ok is True


def test_malformed_frame_does_not_take_the_server_down(server_and_client):
    """A garbage line gets dropped (or returns a protocol error); the
    server keeps accepting connections. A future client mustn't have
    to ``jaeger restart`` because some bad byte hit the socket."""
    server, make_client = server_and_client
    # Send garbage directly via raw socket so the client framing layer
    # can't pre-validate it for us.
    raw = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    raw.connect(str(server.socket_path))
    raw.sendall(b"{not valid json}\n")
    raw.close()

    # The server should still answer a fresh client.
    with make_client() as c:
        resp = c.call("ping")
    assert resp.ok is True


def test_concurrent_clients_each_get_their_own_responses(server_and_client):
    """Two clients sending simultaneously must each get their own
    response back — id matching keeps them from crossing. Phase 1's
    server is thread-per-connection so this is the easy case; we test
    it now because Phase 2 will tighten the model and we want the
    regression net in place."""
    server, make_client = server_and_client
    results: dict[str, P.Response] = {}

    def worker(name: str, n: int):
        with make_client() as c:
            results[name] = c.call("echo", text=name, n=n)

    threads = [threading.Thread(target=worker, args=(name, i))
               for i, name in enumerate(["a", "b", "c", "d"])]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)
        assert not t.is_alive(), "worker hung"

    assert set(results.keys()) == {"a", "b", "c", "d"}
    for name, resp in results.items():
        assert resp.ok is True
        assert resp.result["text"] == name


# ── lifecycle ──────────────────────────────────────────────────────


def test_stop_removes_the_socket_file(short_tmp):
    """A clean ``stop()`` unbinds and unlinks the socket — the next
    ``start()`` on the same path doesn't fail with EADDRINUSE."""
    sock_path = short_tmp / "jaeger.sock"
    s1 = Server(socket_path=sock_path)
    s1.start()
    assert sock_path.exists()
    s1.stop()
    assert not sock_path.exists(), "socket file should be removed on stop"

    # Re-bind on the same path works.
    s2 = Server(socket_path=sock_path)
    s2.start()
    assert sock_path.exists()
    s2.stop()


def test_client_connect_failure_is_a_clean_error(short_tmp):
    """Pointing the client at a socket that doesn't exist (daemon not
    running) raises a typed ``DaemonNotRunning`` — not a generic
    ConnectionRefusedError that the tray/CLI would have to parse."""
    from jaeger_os.daemon.client import DaemonNotRunning

    sock_path = short_tmp / "nope.sock"
    with pytest.raises(DaemonNotRunning):
        with Client(socket_path=sock_path) as c:
            c.call("ping")


def test_custom_handler_can_be_registered(short_tmp):
    """The lifecycle layer (Phase 1.4) registers ops for real agent
    work; the server has to expose a public registration point."""
    sock_path = short_tmp / "jaeger.sock"
    server = Server(socket_path=sock_path)
    server.register("double", lambda **kw: {"value": kw["n"] * 2})
    server.start()
    try:
        for _ in range(50):
            if sock_path.exists():
                break
            time.sleep(0.01)
        with Client(socket_path=sock_path) as c:
            resp = c.call("double", n=21)
        assert resp.ok is True
        assert resp.result == {"value": 42}
    finally:
        server.stop()
