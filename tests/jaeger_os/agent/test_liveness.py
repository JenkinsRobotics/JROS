"""Phase-8 liveness instrumentation — stale-call detector + heartbeat.

The heartbeat surfaces "still working" status to the TUI / gateway
while the model is generating; the stale detector trips when a
provider's socket is open but no bytes are flowing, so the
adapter-fallback chain can react in ~30s instead of waiting out the
SDK's full timeout.
"""

from __future__ import annotations

import threading
import time

import pytest

from jaeger_os.agent import (
    AgentCallbacks,
    JaegerAgent,
    ProviderAdapter,
    StaleCallTimeout,
    clear_registry,
    interruptible_call,
)


# ── interruptible_call: stale + heartbeat ──────────────────────────


def test_stale_timeout_fires_when_call_hangs():
    """The wrapped call sleeps forever; the detector raises after the
    timeout passes."""
    ev = threading.Event()

    def _hang() -> str:
        time.sleep(5.0)
        return "should not reach"

    with pytest.raises(StaleCallTimeout, match="no response after"):
        interruptible_call(
            _hang, ev, poll_interval=0.05, stale_timeout=0.3,
        )


def test_no_stale_timeout_when_call_returns_fast():
    """Fast call: stale_timeout never fires."""
    ev = threading.Event()
    out = interruptible_call(
        lambda: 42, ev, poll_interval=0.01, stale_timeout=1.0,
    )
    assert out == 42


def test_stale_timeout_none_means_unbounded():
    """Stale-timeout=None disables the detector — long calls succeed."""
    ev = threading.Event()

    def _slow() -> str:
        time.sleep(0.3)
        return "done"

    out = interruptible_call(_slow, ev, poll_interval=0.05, stale_timeout=None)
    assert out == "done"


def test_heartbeat_fires_during_call_and_reports_elapsed():
    """Heartbeat ticks during in-flight calls; elapsed_s grows on
    each tick."""
    ev = threading.Event()
    ticks: list[float] = []

    def _slow() -> str:
        time.sleep(0.35)
        return "done"

    out = interruptible_call(
        _slow, ev, poll_interval=0.05,
        on_heartbeat=lambda elapsed: ticks.append(elapsed),
    )
    assert out == "done"
    # Several heartbeats fired; the last is approximately 0.35s.
    assert len(ticks) >= 3
    assert ticks[0] < ticks[-1]
    assert ticks[-1] >= 0.2


def test_heartbeat_exception_does_not_break_call():
    """A buggy heartbeat callback must NEVER break the wrapped call."""
    ev = threading.Event()

    def _slow() -> str:
        time.sleep(0.15)
        return "done"

    def _broken(_elapsed):
        raise RuntimeError("heartbeat bug")

    out = interruptible_call(
        _slow, ev, poll_interval=0.05, on_heartbeat=_broken,
    )
    assert out == "done"


def test_interrupt_still_wins_over_stale_timeout():
    """When the interrupt event fires before stale_timeout, raise
    AgentInterrupted — operator cancel takes priority over the hang
    detector."""
    from jaeger_os.agent import AgentInterrupted

    ev = threading.Event()

    def _hang() -> str:
        time.sleep(5.0)
        return ""

    def _set_interrupt():
        time.sleep(0.1)
        ev.set()

    threading.Thread(target=_set_interrupt, daemon=True).start()
    with pytest.raises(AgentInterrupted):
        interruptible_call(_hang, ev, poll_interval=0.02, stale_timeout=2.0)


# ── JaegerAgent integration ────────────────────────────────────────


class _SlowAdapter(ProviderAdapter):
    """Sleeps for ``hang_for`` seconds in ``call``; tracks
    ``stale_timeout`` and ``on_heartbeat`` kwargs received."""

    name = "slow"

    def __init__(self, hang_for: float = 0.0) -> None:
        self.hang_for = hang_for
        self.last_stale_timeout: float | None | object = object()
        self.last_on_heartbeat: object | None = object()

    def format_messages(self, messages, tools, system):  # noqa: ARG002
        return {"messages": messages}

    def call(self, formatted, interrupt_event, *,
             stale_timeout=None, on_heartbeat=None, **kwargs):  # noqa: ARG002
        self.last_stale_timeout = stale_timeout
        self.last_on_heartbeat = on_heartbeat
        if self.hang_for:
            time.sleep(self.hang_for)
        # Forward calls to the heartbeat so the activity timestamp updates.
        if on_heartbeat is not None:
            on_heartbeat(0.05)
        return {"role": "assistant", "content": "ok"}

    def parse_response(self, raw):
        return raw

    def supports(self, feature):  # noqa: ARG002
        return False


@pytest.fixture(autouse=True)
def _isolate_registry():
    clear_registry()
    yield
    clear_registry()


def test_agent_threads_stale_timeout_through_to_adapter():
    """``JaegerAgent.stale_call_timeout_s`` reaches the adapter."""
    adapter = _SlowAdapter()
    agent = JaegerAgent(adapter=adapter)
    agent.run_turn("hi")
    assert adapter.last_stale_timeout == agent.stale_call_timeout_s


def test_agent_threads_heartbeat_callback_through_to_adapter():
    """A user-supplied heartbeat callback flows from
    ``AgentCallbacks.heartbeat`` to the adapter's ``on_heartbeat`` arg."""
    ticks: list[float] = []
    cb = AgentCallbacks(heartbeat=lambda e: ticks.append(e))
    adapter = _SlowAdapter()
    agent = JaegerAgent(adapter=adapter, callbacks=cb)
    agent.run_turn("hi")
    # The adapter forwarded the heartbeat once during call.
    assert ticks == [0.05]


def test_agent_last_activity_ts_updates_on_heartbeat():
    """The agent's ``last_activity_ts`` is touched by every heartbeat
    so the TUI / gateway can read 'last seen' time."""
    adapter = _SlowAdapter()
    agent = JaegerAgent(adapter=adapter)
    before = time.time()
    agent.run_turn("hi")
    after = time.time()
    assert before <= agent.last_activity_ts <= after
    assert "model" in agent.last_activity_desc


def test_touch_activity_updates_timestamp_and_description():
    """The public ``touch_activity`` lets tools and callbacks signal
    progress between model calls."""
    adapter = _SlowAdapter()
    agent = JaegerAgent(adapter=adapter)
    agent.touch_activity("downloading model from hub")
    assert agent.last_activity_desc == "downloading model from hub"
    assert agent.last_activity_ts > 0


def test_stale_timeout_disabled_when_set_to_none():
    """Setting ``stale_call_timeout_s = None`` on the agent passes
    ``None`` to the adapter, disabling the detector."""
    adapter = _SlowAdapter()
    agent = JaegerAgent(adapter=adapter)
    agent.stale_call_timeout_s = None
    agent.run_turn("hi")
    assert adapter.last_stale_timeout is None


def test_stale_timeout_triggers_fallback_chain():
    """When the primary hangs past stale_timeout, the agent moves on
    to the next fallback adapter without raising to the caller."""
    primary = _SlowAdapter(hang_for=0.6)  # will trip the detector
    backup = _SlowAdapter(hang_for=0.0)
    agent = JaegerAgent(adapter=primary, fallback_adapters=[backup])
    agent.stale_call_timeout_s = 0.2
    result = agent.run_turn("hi")
    # Backup served the response.
    assert result == "ok"
