"""jaeger_os.nodes.tts — the TTS node package.

Per-subsystem package shape (matches VoiceLLM's stt/ + tts/ + audio/
layout and JROS's own skills/ pattern).  Components that belong with
the TTS node — SSML preprocessing, voice-resolver helpers, future
backend adapters — live as siblings of ``node.py`` here rather than
polluting the top of ``jaeger_os/nodes/``.
"""

from typing import Any

from .node import Synthesizer, TTSNode

__all__ = ["TTSNode", "Synthesizer", "make_tts_node"]


def make_tts_node(bus: Any, config: dict[str, Any]) -> TTSNode:
    """Chassis-contract factory ``(bus, config) -> TTSNode``.

    0.8 U3b: constructs the node DIRECTLY on the chassis-injected
    ``bus`` via ``runtime._build_tts_node`` rather than calling
    ``ensure_tts_node()`` — the supervisor's ``ThreadHandle`` invokes
    this factory from inside ``ThreadHandle.start()``, and
    ``ensure_tts_node()``'s supervisor-delegation branch would call
    right back into ``supervisor.start("tts")``, recursing into the
    very ``start()`` call this factory is running inside of. See
    ``jaeger_os/nodes/runtime.py``'s ``_build_tts_node`` docstring.
    """
    from jaeger_os.nodes.runtime import _build_tts_node
    return _build_tts_node(bus, config)
