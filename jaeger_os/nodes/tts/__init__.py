"""jaeger_os.nodes.tts — the TTS node package.

Per-subsystem package shape (matches VoiceLLM's stt/ + tts/ + audio/
layout and JROS's own skills/ pattern).  Components that belong with
the TTS node — SSML preprocessing, voice-resolver helpers, future
backend adapters — live as siblings of ``node.py`` here rather than
polluting the top of ``jaeger_os/nodes/``.
"""

from .node import Synthesizer, TTSNode

__all__ = ["TTSNode", "Synthesizer"]
