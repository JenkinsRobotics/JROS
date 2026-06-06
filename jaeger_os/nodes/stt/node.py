"""node.py — STT node.

Wraps the existing :class:`WhisperSTTContinuous` engine as a Bus-
publishing node.  Owns the mic + Whisper instance; polls for
committed phrases and publishes :class:`Transcript` messages on
``/sense/transcript`` so the brain (and any other interested node)
can subscribe.

Why STT owns the mic for now
----------------------------
The canonical 0.4 architecture has a separate ``audio_io`` node
that publishes ``/sense/audio_in`` (raw mic frames) which STT then
subscribes to.  We haven't built audio_io yet — the existing
Whisper plugin already does its own mic capture + VAD + energy
gating + buffer management end-to-end, and refactoring that out
of WhisperSTTContinuous would be a major rewrite for marginal
benefit before we actually want to swap the audio source.

So Track B.3 = "STT owns the mic" as the simplest viable wiring
that demonstrates the node-shape.  Track B.4 (later) can split
audio_io out cleanly — at that point STT just changes from owning
a ``_MicStream`` to subscribing to ``/sense/audio_in``; everything
above WhisperSTTContinuous (the node, the topic, the brain
contract) is unchanged.

Threading
---------
The STT engine has its own background thread (started by
``adapter.start()`` in ``setup()``) that runs the mic + Whisper
loop.  The node's ``tick()`` only POLLS the engine's committed-
phrase queue via ``next_phrase(timeout=0.5)`` — short blocks so
stop() responsive, no busy-loop.  Phrases get published from the
tick.
"""

from __future__ import annotations

from typing import Any, Protocol

from jaeger_os import topics
from jaeger_os.nodes.base import Node
from jaeger_os.transport import Bus


class STTAdapter(Protocol):
    """The bit of :class:`WhisperSTTContinuous` the STT node depends
    on.  Production callers pass the real Whisper engine.  Tests
    pass a mock that returns canned phrases.

    Note: ``start`` opens the mic; ``stop`` closes it.  Both are
    required to be idempotent enough that signal-triggered teardown
    doesn't crash even if start hasn't run yet.
    """

    def start(self) -> None:
        """Begin capture + transcription loop.  Long-lived
        background thread inside the adapter."""
        ...

    def stop(self) -> None:
        """Tear down capture + transcription.  Should not raise."""
        ...

    def next_phrase(self, timeout: float | None = 1.0) -> str | None:
        """Block up to ``timeout`` seconds for the next committed
        phrase.  Returns the transcript text, or ``None`` on
        timeout."""
        ...


class STTNode(Node):
    """Poll an :class:`STTAdapter` for committed phrases; publish
    :class:`Transcript` on ``/sense/transcript``.

    Today the brain doesn't subscribe to ``/sense/transcript`` yet
    (the voice loop still calls ``next_phrase`` directly via its
    own STT instance).  That migration is Track B.3.2 — when it
    lands the voice loop subscribes here instead, and the STT
    engine has one owner (this node) rather than the voice loop
    keeping its own.

    Backpressure
    ------------
    None at this layer.  The adapter's own ``_committed_q`` is the
    bounded queue between Whisper's transcribe loop and this node's
    tick().  If the brain falls behind reading ``/sense/transcript``
    that's a Bus-level concern, not an STT concern.
    """

    def __init__(
        self,
        *,
        bus: Bus,
        adapter: STTAdapter,
        name: str = "stt",
        poll_timeout_s: float = 0.5,
        install_signal_handlers: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            name=name,
            install_signal_handlers=install_signal_handlers,
        )
        self.adapter = adapter
        self._poll_timeout_s = poll_timeout_s

    # ── lifecycle ─────────────────────────────────────────────────

    def setup(self) -> None:
        """Open the mic + start the Whisper background loop."""
        self.adapter.start()
        self._log(f"adapter started; will publish {topics.SENSE_TRANSCRIPT}")

    def tick(self) -> None:
        """Pull one committed phrase per tick (blocking up to
        ``poll_timeout_s``); publish it as a :class:`Transcript`.
        Empty polls return quickly so stop() stays responsive."""
        phrase = self.adapter.next_phrase(timeout=self._poll_timeout_s)
        if not phrase:
            return
        self.bus.publish(topics.Transcript(
            text=phrase,
            is_final=True,
            language="en",
            node_id=self.name,
        ))

    def teardown(self) -> None:
        """Close the mic + stop the Whisper loop.  Idempotent."""
        try:
            self.adapter.stop()
        except Exception as exc:  # noqa: BLE001
            self._log(f"adapter stop error: {type(exc).__name__}: {exc}")
