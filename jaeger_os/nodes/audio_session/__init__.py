"""jaeger_os.nodes.audio_session — realtime voice-input node package."""

from typing import Any

from .node import AudioSessionNode, STTAdapter, STTNode

__all__ = [
    "AudioSessionNode", "STTNode", "STTAdapter",
    "make_audio_session_node",
]


def make_audio_session_node(bus: Any, config: dict[str, Any]) -> AudioSessionNode:
    """Chassis-contract factory ``(bus, config) -> AudioSessionNode``.

    0.8 U3b: constructs the node DIRECTLY on the chassis-injected
    ``bus`` via ``runtime._build_audio_session_node`` rather than
    calling ``ensure_audio_session_node()`` — same recursion hazard as
    ``make_tts_node`` (the supervisor's ``ThreadHandle.start()`` calls
    this factory; ``ensure_audio_session_node()``'s supervisor branch
    would call right back into ``supervisor.start("audio_session")``).

    The audio session has heavy config (``AudioSessionConfig``
    dataclass) that the runtime singleton expects; this still passes
    ``AudioSessionConfig()`` defaults — routing the manifest's
    config_key slice through the dataclass is future work, unrelated
    to 0.8 U3b's supervisor-ownership change.
    """
    from jaeger_os.nodes.runtime import _build_audio_session_node
    return _build_audio_session_node(bus, config)
