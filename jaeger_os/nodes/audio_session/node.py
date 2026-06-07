"""Audio session node.

Owns the realtime voice-input session and publishes semantic bus events:
finalized transcripts on ``/sense/transcript`` and low-latency speech
start on ``/sense/user_speech_start``.

The node deliberately keeps mic frames, AEC, VAD, and STT buffering
inside one in-process realtime subsystem.  In monolithic mode it may
share the TTS synthesizer's ``reference_buffer`` object directly through
``runtime.get_synth().reference_buffer`` during session construction.
That is a known monolithic-only coupling; multiprocess mode should move
the far-end reference to a dedicated binary topic when it needs to cross
process boundaries.
"""

from __future__ import annotations

from jaeger_os import topics
from jaeger_os.core.audio import AudioSession, STTAdapter
from jaeger_os.nodes.base import Node
from jaeger_os.transport import Bus


class AudioSessionNode(Node):
    """Poll an :class:`AudioSession` for committed phrases.

    ``AudioSession`` owns mic/AEC/VAD/STT control.  This node owns the
    bus contract around that session.
    """

    def __init__(
        self,
        *,
        bus: Bus,
        session: AudioSession | None = None,
        adapter: STTAdapter | None = None,
        name: str = "audio_session",
        poll_timeout_s: float = 0.5,
        install_signal_handlers: bool = False,
    ) -> None:
        super().__init__(
            bus=bus,
            name=name,
            install_signal_handlers=install_signal_handlers,
        )
        if session is None:
            if adapter is None:
                raise TypeError("AudioSessionNode requires session or adapter")
            session = AudioSession(adapter=adapter)
        self.session = session
        self._poll_timeout_s = poll_timeout_s

    # ── lifecycle ─────────────────────────────────────────────────

    def setup(self) -> None:
        """Open the mic + start the STT background loop."""
        self.session.set_on_speech_detected(self._publish_user_speech_start)
        self.session.start()
        self._log(
            "audio session started; will publish "
            f"{topics.SENSE_TRANSCRIPT} + {topics.SENSE_USER_SPEECH_START}"
        )

    def tick(self) -> None:
        """Pull one committed phrase per tick and publish it as a
        :class:`Transcript`."""
        phrase = self.session.next_phrase(timeout=self._poll_timeout_s)
        if not phrase:
            return
        self.bus.publish(topics.Transcript(
            text=phrase,
            is_final=True,
            language="en",
            node_id=self.name,
        ))

    def teardown(self) -> None:
        """Close the mic + stop STT.  Idempotent."""
        try:
            self.session.set_on_speech_detected(None)
        except Exception:  # noqa: BLE001
            pass
        try:
            self.session.stop()
        except Exception as exc:  # noqa: BLE001
            self._log(f"audio session stop error: {type(exc).__name__}: {exc}")

    def _publish_user_speech_start(self) -> None:
        self.bus.publish(topics.UserSpeechStart(node_id=self.name))


# Back-compat aliases for one release while downstream imports move.
STTNode = AudioSessionNode

__all__ = ["AudioSessionNode", "STTNode", "STTAdapter"]
