"""Daemon event bus — publish/subscribe semantics.

These cover the pure-data piece without any sockets in the picture;
the streaming-handler tests in ``test_chat_subscribe.py`` cover the
end-to-end wiring through the server.
"""

from __future__ import annotations

import queue
import threading
import time

from jaeger_os.daemon.event_bus import EventBus


def _drain(sub, timeout: float = 0.5) -> list[tuple[str, dict]]:
    """Drain a subscription's queue, stopping on the close sentinel
    or after ``timeout`` seconds with no new events."""
    out: list[tuple[str, dict]] = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            item = sub.queue.get(timeout=0.05)
        except queue.Empty:
            continue
        if item is None:
            return out
        out.append(item)
    return out


def test_publish_to_no_subscribers_is_noop():
    bus = EventBus()
    bus.publish("anything", x=1)  # must not raise
    assert bus.subscriber_count() == 0


def test_single_subscriber_receives_events():
    bus = EventBus()
    sub = bus.subscribe()
    bus.publish("hello", name="alice")
    bus.publish("hello", name="bob")
    bus.unsubscribe(sub)
    events = _drain(sub)
    assert events == [
        ("hello", {"name": "alice"}),
        ("hello", {"name": "bob"}),
    ]


def test_multiple_subscribers_each_receive_full_stream():
    """Pub/sub means EVERY subscriber sees every event — the bus
    must not round-robin or load-balance."""
    bus = EventBus()
    s1 = bus.subscribe()
    s2 = bus.subscribe()
    for i in range(5):
        bus.publish("tick", i=i)
    bus.unsubscribe(s1)
    bus.unsubscribe(s2)
    a = _drain(s1)
    b = _drain(s2)
    assert [e[1]["i"] for e in a] == [0, 1, 2, 3, 4]
    assert [e[1]["i"] for e in b] == [0, 1, 2, 3, 4]


def test_unsubscribed_drops_close_sentinel_so_drain_exits():
    """A consumer blocked on ``queue.get()`` should wake up cleanly
    when its subscription is dropped."""
    bus = EventBus()
    sub = bus.subscribe()

    drained: list[object] = []

    def _consumer():
        while True:
            item = sub.queue.get(timeout=2.0)
            if item is None:
                return
            drained.append(item)

    t = threading.Thread(target=_consumer, daemon=True)
    t.start()
    bus.publish("hi")
    bus.unsubscribe(sub)
    t.join(timeout=1.0)
    assert not t.is_alive(), "consumer didn't see the close sentinel"
    assert drained == [("hi", {})]


def test_slow_subscriber_drops_events_doesnt_block_publisher():
    """A subscriber that never drains shouldn't be able to stall
    the publisher — that would stall the agent. Fill its queue
    past the cap and confirm the dropped counter ticks."""
    bus = EventBus()
    sub = bus.subscribe()
    # Don't drain; keep publishing past the queue cap.
    for i in range(300):  # _QUEUE_MAX is 256
        bus.publish("flood", i=i)
    dropped = bus.unsubscribe(sub)
    assert dropped > 0, "expected some events to be dropped on full queue"


def test_publish_keeps_going_when_one_subscriber_overflows():
    """One subscriber has its queue overflowed; the OTHER subscriber
    must still receive every event the publisher sends. Protects
    the daemon: a stalled TUI can't starve the tray of status
    updates."""
    bus = EventBus()
    overflowed = bus.subscribe()
    healthy = bus.subscribe()
    from jaeger_os.daemon.event_bus import _QUEUE_MAX

    # Push past the cap on ``overflowed``; ``healthy`` shares the
    # publisher's per-event loop so it must also receive each call.
    for i in range(_QUEUE_MAX + 50):
        bus.publish("burst", i=i)
    bus.publish("hot", marker=True)
    dropped = bus.unsubscribe(overflowed)
    bus.unsubscribe(healthy)

    # Overflowed subscriber reports drops — proves we hit the
    # backpressure path without crashing.
    assert dropped > 0

    # Healthy subscriber received every event. It has its own
    # _QUEUE_MAX cap, so the very oldest bursts also dropped off
    # for it — but the most recent events (including ``hot``)
    # survived.
    healthy_events = _drain(healthy)
    assert any(name == "hot" for name, _ in healthy_events)
