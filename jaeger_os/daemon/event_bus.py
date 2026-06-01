"""Tiny thread-safe pub/sub bus for daemon-side events.

The bus is a daemon-process singleton (stashed on
``main._pipeline['daemon_event_bus']``) so the agent's per-turn
callbacks can publish without knowing about the daemon, and any
number of client connections can subscribe via ``chat.subscribe`` and
receive a live stream of tool-activity / status events.

Why so small
------------
Two reasons not to reach for a queue library here:

  * The fan-out is tiny — typically 1-3 subscribers (TUI, tray, maybe
    a GUI). A ``list`` of callables under a single ``threading.Lock``
    is more than fast enough; there's no contention story to win.
  * The publisher path runs *inside* the agent's tool-progress
    callback, which is on the LLM hot path. Anything that blocks
    there blocks the model. We keep ``publish`` non-blocking by
    handing each subscriber its own bounded queue + worker thread —
    a slow subscriber can't pause the agent.

Subscriber model
----------------
``subscribe(fn)`` returns a ``Subscription`` token. Each subscription
gets a bounded ``queue.Queue`` and a daemon thread that drains it
into ``fn``. ``publish(name, payload)`` is non-blocking — if a
subscriber's queue is full (slow consumer), the event is dropped for
THAT subscriber and a counter increments. We surface the drop count
on ``unsubscribe`` so a client can log "I missed N events".

The drop-on-full policy is the right trade-off for "live UI" events:
catching up to a stale tool-progress event is useless; the user wants
the latest.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Optional


# Per-subscriber queue size. Big enough to absorb a fast burst of
# tool events during a multi-call turn; small enough that a stuck
# consumer can't grow the daemon's memory footprint forever.
_QUEUE_MAX = 256


EmitFn = Callable[[str, dict[str, Any]], None]


@dataclass
class Subscription:
    """Token returned by :meth:`EventBus.subscribe`. Carries the
    underlying queue so the subscriber's pump thread can drain it,
    and a ``dropped`` counter for events shed while the queue was
    full."""
    id: int
    queue: "queue.Queue[Optional[tuple[str, dict[str, Any]]]]"
    dropped: int = 0
    # ``None`` posted to the queue is the close-sentinel — drain
    # threads exit when they see it.


class EventBus:
    """Thread-safe pub/sub. Many publishers, many subscribers.

    Subscribers are pumped by per-subscription daemon threads so a
    slow consumer can't block the publisher. A bounded queue keeps
    memory in check; overflow drops the oldest events for that
    subscriber and increments the drop counter.
    """

    def __init__(self) -> None:
        self._subs: list[Subscription] = []
        self._lock = threading.Lock()
        self._next_id = 1

    # ── pub side ───────────────────────────────────────────────────

    def publish(self, event, /, **payload: Any) -> None:
        """Push an event to every current subscriber. Non-blocking —
        full queues drop the event for that subscriber and increment
        its ``dropped`` counter.

        ``event`` is positional-only so callers can use any payload
        key name (including ``name``) without colliding with the
        function's own parameter.
        """
        with self._lock:
            subs = list(self._subs)
        for sub in subs:
            try:
                sub.queue.put_nowait((event, dict(payload)))
            except queue.Full:
                # Drop-newest by default would be unfair to the most
                # recent (most relevant) event; drop-oldest preserves
                # liveness. Best-effort discard one and retry.
                try:
                    sub.queue.get_nowait()
                    sub.queue.put_nowait((event, dict(payload)))
                except (queue.Empty, queue.Full):
                    pass
                sub.dropped += 1

    # ── sub side ───────────────────────────────────────────────────

    def subscribe(self) -> Subscription:
        """Register a new subscriber. The caller drains
        ``sub.queue`` and writes each ``(name, payload)`` somewhere
        useful (a socket, a UI widget, a log)."""
        q: "queue.Queue[Optional[tuple[str, dict[str, Any]]]]" = queue.Queue(maxsize=_QUEUE_MAX)
        with self._lock:
            sub = Subscription(id=self._next_id, queue=q)
            self._next_id += 1
            self._subs.append(sub)
        return sub

    def unsubscribe(self, sub: Subscription) -> int:
        """Drop a subscription. Returns the count of events that were
        dropped while it was alive — useful for "you missed N events"
        log lines. Posts a close-sentinel so the consumer's drain
        thread exits cleanly."""
        with self._lock:
            try:
                self._subs.remove(sub)
            except ValueError:
                pass
        try:
            sub.queue.put_nowait(None)
        except queue.Full:
            # Pump it out and retry — the close sentinel must land.
            try:
                sub.queue.get_nowait()
                sub.queue.put_nowait(None)
            except (queue.Empty, queue.Full):
                pass
        return sub.dropped

    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subs)


__all__ = ["EventBus", "Subscription", "EmitFn"]
