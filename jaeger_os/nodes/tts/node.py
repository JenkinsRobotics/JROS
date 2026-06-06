"""tts.py — TTS node.  First Track B node.

Wraps the existing in-process :class:`KokoroTTS` engine as a Bus-
addressable node.  Subscribes to ``/act/speech`` (the brain's
text-to-speech command topic), runs synthesis + playback on the
node's own work thread, and publishes ``/sense/spoken`` as the ack
the brain's ``text_to_speech`` tool will await (Track B.2).

Why this is the right "first real node"
---------------------------------------
* TTS has a clean request → ack shape — easiest demonstration of
  the operator's "tools = networking, nodes = execution" contract.
* The existing :class:`KokoroTTS` engine is proven (0.3.0 ships it).
  We're wrapping it, not reimplementing.
* No mic / STT involvement — half the audio pipeline isolated from
  the change.
* Doesn't touch the brain or voice loop in this commit; Track B.2
  is the brain-side rewire (text_to_speech tool publishes /act/speech
  via the bus instead of calling speak() in-process).

Threading
---------
The bus delivery thread MUST NOT block on slow work; otherwise it
back-pressures every other subscriber on every other topic.  TTS
synthesis + playback takes hundreds of ms to seconds, so the
subscriber callback (``_on_speech_command``) only enqueues; the
node's own ``tick()`` drains the queue and runs synthesis serially
on the node thread.

Backpressure
------------
Internal queue is bounded (default 32 messages).  When full, the
new request gets an immediate failure ack (``ok=False``,
``reason="TTS queue full"``) so the brain's tool sees the rejection
right away rather than waiting for a timeout.
"""

from __future__ import annotations

import queue
import time
from typing import Any, Protocol

from jaeger_os import topics
from jaeger_os.nodes.base import Node
from jaeger_os.transport import Bus


class Synthesizer(Protocol):
    """The bit of :class:`KokoroTTS` the TTS node depends on.

    Production callers pass the real ``KokoroTTS`` instance.  Tests
    pass a mock that records calls and returns canned results.
    """

    def speak(self, text: str) -> dict[str, Any]:
        """Synthesize + play ``text``; block until playback finishes.
        Returns a dict with at least ``spoken: bool``; may also carry
        ``elapsed_s``, ``reason`` (when ok=False), ``text`` (cleaned),
        ``samples``."""
        ...

    def shutdown(self) -> None:
        """Tear the synthesizer down cleanly (close audio device,
        unload model)."""
        ...


class TTSNode(Node):
    """SUB ``/act/speech`` → synthesize → PUB ``/sense/spoken``.

    The synthesizer is dependency-injected so tests can substitute a
    mock without touching audio or model loading.  Production
    instantiation lives in ``dev_scripts/tts_node_test.py`` (the
    integration smoke) and at Track B.2 will move to the brain's
    boot path so the ``text_to_speech`` tool can route through the
    bus instead of calling KokoroTTS in-process.
    """

    def __init__(
        self,
        *,
        bus: Bus,
        synthesizer: Synthesizer,
        name: str = "tts",
        queue_maxsize: int = 32,
        install_signal_handlers: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            name=name,
            install_signal_handlers=install_signal_handlers,
        )
        self.synthesizer = synthesizer
        # Per-message handoff from bus delivery thread → node thread.
        self._pending: "queue.Queue[topics.SpeechCommand]" = queue.Queue(
            maxsize=queue_maxsize,
        )

    # ── lifecycle ─────────────────────────────────────────────────

    def setup(self) -> None:
        self.bus.subscribe(topics.ACT_SPEECH, self._on_speech_command)
        self._log(f"subscribed to {topics.ACT_SPEECH}")

    def tick(self) -> None:
        """Drain one queued speech request per tick.  Synthesis runs
        synchronously on this thread; the next tick won't start until
        the current speech finishes playing."""
        try:
            msg = self._pending.get(timeout=0.1)
        except queue.Empty:
            return
        self._handle(msg)

    def teardown(self) -> None:
        try:
            self.bus.unsubscribe(topics.ACT_SPEECH, self._on_speech_command)
        except Exception:  # noqa: BLE001
            pass
        if self.synthesizer is not None:
            try:
                self.synthesizer.shutdown()
            except Exception as exc:  # noqa: BLE001
                self._log(f"synthesizer shutdown error: "
                          f"{type(exc).__name__}: {exc}")

    # ── subscriber + worker ──────────────────────────────────────

    def _on_speech_command(self, msg: topics.TopicMessage) -> None:
        """Called by the bus delivery thread.  Must return quickly —
        delegate slow work to the node tick()."""
        assert isinstance(msg, topics.SpeechCommand), (
            f"TTS node got unexpected topic: {msg.topic}"
        )
        try:
            self._pending.put_nowait(msg)
        except queue.Full:
            # Immediate-fail ack so the brain's tool sees rejection.
            self._publish_ack(
                msg, ok=False, reason="TTS queue full", duration_s=0.0,
            )

    def _handle(self, msg: topics.SpeechCommand) -> None:
        t0 = time.perf_counter()
        try:
            result = self.synthesizer.speak(msg.text)
        except Exception as exc:  # noqa: BLE001
            self._log(f"speak() raised: {type(exc).__name__}: {exc}")
            self._publish_ack(
                msg, ok=False,
                reason=f"{type(exc).__name__}: {exc}",
                duration_s=time.perf_counter() - t0,
            )
            return
        ok = bool(result.get("spoken", False))
        # Prefer the synthesizer's elapsed if it gives one (more
        # accurate — includes synth time, not just playback) but
        # fall back to wall-clock so the brain always gets a number.
        duration_s = float(
            result.get("elapsed_s") or (time.perf_counter() - t0)
        )
        reason = result.get("reason") if not ok else None
        self._publish_ack(msg, ok=ok, duration_s=duration_s, reason=reason)

    def _publish_ack(
        self,
        request: topics.SpeechCommand,
        *,
        ok: bool,
        duration_s: float,
        reason: str | None,
    ) -> None:
        self.bus.publish(topics.SpokenAck(
            ok=ok,
            duration_s=duration_s,
            reason=reason,
            node_id=self.name,
            correlation_id=request.correlation_id,
        ))
