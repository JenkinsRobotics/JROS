"""Daemon chat-ops registry — wires the agent's ``run_turn`` to the
NDJSON socket protocol so any client (TUI / attach / GUI) can speak
to the SAME agent process.

This is the Phase-2 / Group-1 piece of docs/ROADMAP_0.2.0.md. Phase 1
shipped a daemon that owned a socket but no agent; the TUI carried
its own model. Phase 2 inverts that — the daemon owns the model and
the agent; clients are ephemeral.

Verbs registered here
---------------------

``chat.send``
    Request-response. Blocks the connection until the turn finishes;
    returns ``{"text": str, "error": str|None, "tool_activity": [str],
    "elapsed_s": float, "skipped_final": bool}``. Multiple concurrent
    sends serialize on the agent's LLM lock — exactly one turn runs at
    a time, but other ops (``status.snapshot``, ``ping``) keep
    responding because they don't need the lock.

``chat.history``
    Returns the agent's per-session message list (legacy + Phase-9
    dict shape; the client gets both for free). The session key
    defaults to ``"daemon"`` to match what ``chat.send`` uses.

``status.snapshot``
    Read-only state summary — running, uptime, model path, last
    activity, last halt reason, current iteration count, message
    history length. Cheap; doesn't acquire the LLM lock.

Concurrency
-----------
The server gives us one OS thread per connection. We rely on the
existing ``_pipeline['llm_lock']`` (set by ``boot_for_tui`` →
``boot_for_daemon``) to serialize model access — chat.send acquires
it; everything else doesn't. The single shared ``JaegerAgent``
instance per session is built lazily by ``_run_turn`` and persists
across calls; its ``messages`` history grows with every turn.
"""

from __future__ import annotations

import threading
import time
from typing import Any

from jaeger_os.daemon.event_bus import EventBus


# Default session key the daemon uses if a client doesn't pin its
# own. Keeping it named (vs. None) means the per-session agent cache
# in main.py reuses the same JaegerAgent across all calls that don't
# distinguish themselves, which is what users expect — one continuous
# conversation in front of the menu-bar 🤖.
_DAEMON_SESSION_KEY = "daemon"


def register_booting_stubs(server: Any, progress: dict[str, Any]) -> None:
    """Wire stub chat / status ops onto ``server`` BEFORE the agent
    has finished booting.

    The daemon binds its socket fast (so ``jaeger start`` returns
    quickly), then runs ``boot_for_daemon`` on a background thread.
    During that window — typically a few seconds for a small model,
    much longer for a 30 GB GGUF — clients can already connect; we
    want them to see a clear "booting" / "boot failed" signal rather
    than ``unknown op``. The stubs read from a shared ``progress``
    dict the boot worker updates.

    Once boot finishes, :func:`register_chat_ops` replaces these
    stubs with the production handlers via ``replace=True``.
    """

    def _booting_error(**_: Any) -> dict[str, Any]:
        err = progress.get("error")
        if err:
            return {"error": f"agent boot failed: {err}"}
        return {"error": "agent is still booting"}

    def _snapshot_stub(**_: Any) -> dict[str, Any]:
        return {
            "running": True,
            "agent_ready": False,
            "boot_error": progress.get("error"),
            "uptime_s": time.time() - progress.get("started_at", time.time()),
        }

    server.register("chat.send", _booting_error)
    server.register("chat.history", _booting_error)
    server.register("status.snapshot", _snapshot_stub)


def _make_audit_hooks(layout: Any) -> tuple[Any, Any]:
    """Build (on_connect, on_disconnect) callbacks that append to
    ``<instance>/logs/audit.log`` so the daemon keeps a record of
    "who's been watching" (DAEMON-E in docs/ROADMAP_0.2.0.md).

    Each entry is one JSON line — same shape as the rest of the
    audit log (see ``core/tools/_common.py:_audit``) so existing
    log-rotation + the tamper-evident tooling apply unchanged.
    """
    import json
    from datetime import datetime, timezone

    def _append(event: str, meta: dict[str, Any]) -> None:
        try:
            logs_dir = layout.logs_dir
            logs_dir.mkdir(parents=True, exist_ok=True)
            entry = {
                "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "event": event,
                "client_id": meta.get("client_id"),
                "duration_s": meta.get("duration_s"),
                "ops_called": list(meta.get("ops_called", [])),
            }
            with layout.audit_log_path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=True, default=str) + "\n")
        except Exception:  # noqa: BLE001 — audit must never crash anything
            pass

    def on_connect(meta: dict[str, Any]) -> None:
        _append("daemon.client.connect", meta)

    def on_disconnect(meta: dict[str, Any]) -> None:
        _append("daemon.client.disconnect", meta)

    return on_connect, on_disconnect


def register_chat_ops(server: Any, boot_result: Any) -> None:
    """Wire chat / status verbs onto ``server`` using ``boot_result``.

    ``server`` is a ``daemon.server.Server`` instance; ``boot_result``
    is the :class:`TUIBootResult` from :func:`main.boot_for_daemon`.
    Always replaces any previously-registered handlers (the
    ``register_booting_stubs`` set), so the boot worker can call this
    once boot completes without colliding with the stubs.

    Also installs the connect / disconnect audit hooks so each
    client session leaves a footprint in ``<instance>/logs/audit.log``.
    """
    # Import lazily so the daemon module doesn't pay the import cost of
    # the agent / model machinery just to surface ``ping``. The factory
    # below calls register_chat_ops AFTER boot finishes, so by then
    # main.py is fully loaded anyway.
    from jaeger_os import main as _main
    from jaeger_os.core.instance.instance import touch_manifest_started

    client = boot_result.client
    layout = boot_result.layout
    started_at = time.time()
    snapshot_state: dict[str, Any] = {
        "last_user_text": None,
        "last_answer_text": None,
        "last_turn_at": None,
        "last_elapsed_s": None,
        "last_halt_reason": None,
        "turns_completed": 0,
    }
    # Guards mutation of snapshot_state — short critical section, no
    # contention with the LLM lock.
    snap_lock = threading.Lock()

    # Daemon-wide event bus. The agent's tool-progress callbacks
    # publish through this; every ``chat.subscribe`` connection
    # subscribes to it and pumps events down its socket. We stash
    # the bus on ``_main._pipeline`` so the per-session callback
    # constructor in ``_run_turn_via_jaeger_agent`` can find it
    # without explicit threading.
    bus = EventBus()
    _main._pipeline["daemon_event_bus"] = bus

    def _do_turn(text: str, session_key: str | None) -> dict[str, Any]:
        key = session_key or _DAEMON_SESSION_KEY
        # Bookend the turn with bus events so subscribers can show
        # "thinking…" and "ready" indicators. The per-tool events
        # come from _tool_progress inside _run_turn_via_jaeger_agent.
        bus.publish("turn.start", session_key=key, text=text)
        out = _main._run_turn(client, text, session_key=key)
        with snap_lock:
            snapshot_state["last_user_text"] = text
            snapshot_state["last_answer_text"] = out.get("text") or ""
            snapshot_state["last_turn_at"] = time.time()
            snapshot_state["last_elapsed_s"] = out.get("elapsed_s")
            snapshot_state["last_halt_reason"] = _extract_halt_reason(key)
            snapshot_state["turns_completed"] += 1
        result = {
            "text": out.get("text") or "",
            "error": out.get("error"),
            "tool_activity": out.get("tool_activity") or [],
            "elapsed_s": out.get("elapsed_s"),
            "skipped_final": bool(out.get("skipped_final")),
            "session_key": key,
        }
        # ``result`` already carries ``session_key``; pass it as a
        # whole payload to avoid the kwargs collision.
        bus.publish("turn.complete", **result)
        return result

    def _extract_halt_reason(session_key: str) -> str | None:
        # The per-session JaegerAgent is cached in _run_turn_via_jaeger_agent;
        # poke at it for the most recent halt reason. Best-effort — returns
        # None if the cache hasn't been populated yet.
        cache = getattr(_main, "_jaeger_agents_by_session", {})
        agent = cache.get(session_key) if isinstance(cache, dict) else None
        return getattr(agent, "last_halt_reason", None)

    def _do_history(session_key: str | None = None, limit: int | None = None) -> dict[str, Any]:
        key = session_key or _DAEMON_SESSION_KEY
        cache = getattr(_main, "_jaeger_agents_by_session", {})
        agent = cache.get(key) if isinstance(cache, dict) else None
        msgs = list(getattr(agent, "messages", []) or [])
        if limit is not None and limit > 0:
            msgs = msgs[-limit:]
        # Normalize to JSON-able dicts. JaegerAgent stores Phase-9
        # dict messages already, but we copy defensively so a client
        # mutation can't ripple back into the live history.
        return {
            "session_key": key,
            "messages": [dict(m) if isinstance(m, dict) else {"raw": str(m)} for m in msgs],
            "count": len(msgs),
        }

    def _do_snapshot() -> dict[str, Any]:
        cfg = _main._pipeline.get("config")
        model_path = getattr(getattr(cfg, "model", None), "model_path", None)
        ctx = getattr(getattr(cfg, "model", None), "ctx", None)
        with snap_lock:
            snap = dict(snapshot_state)
        return {
            "running": True,
            "uptime_s": time.time() - started_at,
            "started_at": started_at,
            "instance": str(layout.root) if layout is not None else None,
            # ``model_path`` can be a Path object (Pydantic coerces
            # ``model.path`` in some config variants); stringify
            # defensively so JSON-encode never tips over.
            "model_path": str(model_path) if model_path is not None else None,
            "ctx": ctx,
            **snap,
        }

    def _do_subscribe(emit: Any, **_: Any) -> dict[str, Any]:
        """Streaming handler — block this connection, pumping events
        from the daemon bus down the socket as they arrive. Returns
        when the client disconnects (the next bus drain pushes a
        sentinel that breaks the loop)."""
        sub = bus.subscribe()
        # Emit a "subscribed" marker so the client can confirm the
        # subscription is live before any agent activity starts.
        emit("subscribed", subscription_id=sub.id)
        try:
            while True:
                item = sub.queue.get()  # blocks until next event or close
                if item is None:
                    break
                name, payload = item
                emit(name, **payload)
        finally:
            dropped = bus.unsubscribe(sub)
        return {"unsubscribed": True, "dropped": dropped}

    server.register(
        "chat.send",
        lambda text="", session_key=None, **_: _do_turn(text, session_key),
        replace=True,
    )
    server.register("chat.history", _do_history, replace=True)
    server.register("status.snapshot", lambda **_: _do_snapshot(), replace=True)
    # ``chat.subscribe`` is streaming — emit() writes Events down the
    # socket as the agent works, the return value (after the client
    # disconnects) becomes the final Response. Use ``replace=True``
    # for symmetry; the booting stubs don't register this name.
    server.register("chat.subscribe", _do_subscribe, streaming=True, replace=True)

    # DAEMON-E — connect/disconnect audit. Hooks are swapped in via
    # ``set_lifecycle_hooks`` so this works whether the Server was
    # constructed with or without callbacks.
    on_connect, on_disconnect = _make_audit_hooks(layout)
    if hasattr(server, "set_lifecycle_hooks"):
        server.set_lifecycle_hooks(on_connect=on_connect, on_disconnect=on_disconnect)

    # Touch the manifest's last_started_at so ``jaeger status`` can show
    # "started at X" from on-disk state, not just from the in-memory
    # server uptime. boot_for_tui() already touches it once; we touch
    # again here to capture the post-boot timestamp for cleanliness.
    try:
        from jaeger_os.core.instance.schemas import load_json, Manifest
        manifest = load_json(layout.manifest_path, Manifest)
        touch_manifest_started(layout, manifest)
    except Exception:  # noqa: BLE001 — best-effort
        pass


__all__ = ["register_chat_ops", "register_booting_stubs"]
