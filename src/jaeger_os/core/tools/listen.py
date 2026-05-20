"""Microphone capture + Whisper transcription as an agent tool.

  • listen(seconds, model)  — record N seconds of mic audio, transcribe,
                              return the text.

A one-shot, atomic alternative to the ``--voice`` daemon. The mic is
opened, recorded, and closed inside the call — no always-on listening,
no background thread. The Whisper model is cached at module level so
repeated calls don't reload weights.
"""

from __future__ import annotations

import time
from typing import Any


# Reuse the same default the voice daemon uses for its "accurate" pass —
# medium.en strikes the sharpest quality/latency balance for English on
# Apple Silicon. Override by passing ``model=...`` on the call.
_DEFAULT_MODEL = "medium.en"
_SAMPLE_RATE = 16000
_MIN_SECONDS = 1
_MAX_SECONDS = 60

# Cache the Whisper model across calls — first call pays the load cost
# (~3-5s for medium.en), subsequent calls are decode-only.
_cached_model: Any = None
_cached_model_name: str | None = None


def _get_model(name: str) -> Any:
    """Lazy-load + memoize the Whisper model. Re-loads when the caller
    asks for a different model name (rare; usually one model per session)."""
    global _cached_model, _cached_model_name
    if _cached_model is not None and _cached_model_name == name:
        return _cached_model
    from pywhispercpp.model import Model
    _cached_model = Model(
        name,
        print_realtime=False,
        print_progress=False,
        single_segment=False,
        no_context=True,
    )
    _cached_model_name = name
    return _cached_model


def listen(seconds: int = 5, model: str = _DEFAULT_MODEL) -> dict[str, Any]:
    """Record ``seconds`` of microphone audio and return the transcript.

    Tier-1 (microphone access). The mic is opened, recorded, and closed
    inside this call — no always-on listening. For the always-on
    conversation loop, launch ``python -m jaeger_os --voice`` instead.

    Returns ``{ok, transcript, seconds, model, elapsed_s}`` on success
    or ``{ok: False, error: ...}`` on capture / transcribe failure.
    """
    if not isinstance(seconds, int) or seconds < _MIN_SECONDS:
        return {"ok": False, "error": f"seconds must be an int >= {_MIN_SECONDS}"}
    if seconds > _MAX_SECONDS:
        return {
            "ok": False,
            "error": f"seconds capped at {_MAX_SECONDS}; longer captures "
                     "should use the --voice daemon",
        }
    try:
        import numpy as np
        import sounddevice as sd
    except ImportError as exc:
        return {
            "ok": False,
            "error": f"audio capture deps missing ({exc}); "
                     "install with `pip install -e \".[voice]\"`",
        }
    try:
        whisper = _get_model(model)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"whisper load failed: {exc}"}

    started = time.perf_counter()
    try:
        # blocking=True so we don't return until the buffer is full
        audio = sd.rec(
            int(seconds * _SAMPLE_RATE),
            samplerate=_SAMPLE_RATE,
            channels=1,
            dtype="float32",
            blocking=True,
        )
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"mic capture failed: {exc}"}

    # pywhispercpp expects a 1D float32 array at 16 kHz.
    samples = np.asarray(audio, dtype="float32").reshape(-1)
    try:
        segments = whisper.transcribe(samples)
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"transcribe failed: {exc}"}

    text = " ".join((s.text or "").strip() for s in segments).strip()
    elapsed = time.perf_counter() - started
    return {
        "ok": True,
        "transcript": text,
        "seconds": seconds,
        "model": model,
        "elapsed_s": round(elapsed, 3),
    }
