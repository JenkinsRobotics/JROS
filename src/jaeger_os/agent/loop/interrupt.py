"""Interruptible call primitive + liveness instrumentation.

The agent loop must be cancellable mid-flight — today for Ctrl-C and
voice barge-in, later for the operator pressing E-stop on a robot. The
HTTP / network call inside an adapter cannot be cancelled cleanly from
outside (SDK clients don't expose cancellation hooks consistently), so
the proven pattern — used verbatim in hermes-agent and elsewhere — is:
run the call on a daemon thread, poll an ``Event``, abandon the thread
if the event fires. The thread cleans itself up when the underlying
socket eventually closes or times out; the user sees an immediate
return.

Phase-8 additions:

  • **Stale-call detector** — when a non-streaming HTTP request hangs
    silently (the provider's TCP socket open, but no bytes flowing),
    we'd previously wait the full SDK ``timeout`` (often 600s) before
    surfacing it. The detector raises ``StaleCallTimeout`` after
    ``stale_timeout`` seconds so the agent's adapter-fallback chain or
    a higher-level retry policy can react fast.

  • **Activity heartbeat** — the optional ``on_heartbeat`` callback
    fires every ``poll_interval`` seconds while the wrapped call is
    in flight. The TUI status bar reads this to surface
    "still waiting on the model (12 s elapsed)…" instead of looking
    frozen, and the gateway uses the same hook to keep its
    inactivity-watchdog awake during long generations.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, TypeVar


T = TypeVar("T")


class AgentInterrupted(Exception):
    """Raised by :func:`interruptible_call` when the interrupt event
    fires before the wrapped call returns. Carries the agent up out of
    the loop so ``JaegerAgent.run_turn`` can bail cleanly."""


class StaleCallTimeout(Exception):
    """Raised by :func:`interruptible_call` when no progress was made
    for ``stale_timeout`` seconds. Distinct from ``AgentInterrupted``
    so the loop's adapter-fallback chain can retry on a sibling
    backend instead of treating it like a user cancel."""


def interruptible_call(
    fn: Callable[[], T],
    interrupt_event: threading.Event,
    *,
    poll_interval: float = 0.1,
    stale_timeout: float | None = None,
    on_heartbeat: Callable[[float], None] | None = None,
) -> T:
    """Run ``fn()`` on a daemon thread while the main thread polls the
    interrupt event + heartbeat + stale timer.

    Returns ``fn``'s result on success; re-raises any exception from
    inside ``fn``; raises :class:`AgentInterrupted` if the interrupt
    event is set; raises :class:`StaleCallTimeout` if ``stale_timeout``
    passes without ``fn`` returning.

    ``on_heartbeat(elapsed_s)`` fires on every poll tick while the
    call is in flight — useful for surfacing "still waiting" status
    to the TUI / gateway. Pass ``None`` to disable.

    The HTTP / SDK call is not cancellable, but abandoning its thread
    is safe: the underlying socket eventually closes, the request is
    discarded, and the operator's interrupt takes effect immediately
    from their point of view. That's good enough for the robot E-stop
    case — the agent stops *acting* on the response, even though one
    last byte may still be in flight.
    """

    box: dict[str, Any] = {}

    def _worker() -> None:
        try:
            box["value"] = fn()
        except BaseException as exc:  # noqa: BLE001 — re-raised below
            box["error"] = exc

    thread = threading.Thread(target=_worker, daemon=True)
    started = time.perf_counter()
    thread.start()

    while thread.is_alive():
        if interrupt_event.is_set():
            # Abandon the thread; it will exit on its own when the
            # socket / SDK call completes.
            raise AgentInterrupted("agent loop was interrupted")
        elapsed = time.perf_counter() - started
        if stale_timeout is not None and elapsed > stale_timeout:
            # Don't kill the thread (we can't safely) — just bail and
            # let the caller pick a different adapter / retry / surface
            # the hang to the user.
            raise StaleCallTimeout(
                f"no response after {elapsed:.1f}s "
                f"(stale_timeout={stale_timeout:.0f}s)"
            )
        if on_heartbeat is not None:
            try:
                on_heartbeat(elapsed)
            except Exception:  # noqa: BLE001 — heartbeat bugs never break the call
                pass
        thread.join(timeout=poll_interval)

    if "error" in box:
        raise box["error"]
    return box["value"]  # type: ignore[no-any-return]


__all__ = ["AgentInterrupted", "StaleCallTimeout", "interruptible_call"]
