"""jaeger_os.nodes.stt — the STT node package.

Per-subsystem layout matching ``jaeger_os/nodes/tts/`` and
VoiceLLM's ``stt/`` / ``tts/`` package shape.  Add backend
adapters, VAD helpers, language detectors etc. as siblings of
``node.py`` here rather than polluting the parent.
"""

from .node import STTAdapter, STTNode

__all__ = ["STTNode", "STTAdapter"]
