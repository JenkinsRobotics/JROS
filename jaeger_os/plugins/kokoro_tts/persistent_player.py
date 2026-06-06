"""Persistent sounddevice output player for the Kokoro TTS plugin.

Direct port of the working pattern from
``dev_tools/audio_smoke/voice_assistant_persistent.py::PersistentPlayer``,
adapted to live inside the plugin.

Design notes
------------
* ONE ``sd.OutputStream`` opens at plugin warm / first speak() and
  stays alive for the whole session.  Closed at process shutdown.
* Audio chunks come in via :meth:`enqueue` and are pulled out of a
  ``queue.Queue`` by the audio callback running on PortAudio's worker
  thread.  No per-utterance stream churn → no audible device
  power-cycle clicks between replies.
* The output device is **resolved live at start() time** via a direct
  CoreAudio query — *not* PortAudio's cached "default", which on macOS
  is whatever sounddevice picked at module-import time (frequently a
  monitor's HDMI audio sink rather than the device the operator's
  Settings → Sound currently points at).

This module deliberately stays sounddevice-only.  An ``avaudio_io``
variant of the same surface will land in a sibling file when we wire
the config-toggle in step 2 of the 0.3.0 refactor.
"""

from __future__ import annotations

import ctypes
import os
import queue
import sys
import threading
from ctypes import POINTER, byref, c_int, c_uint32, c_void_p, sizeof
from typing import Any, Optional

import numpy as np


# ── live macOS default output lookup ──────────────────────────────────
#
# PortAudio caches "default" at process start; the OS user can change
# their output device anytime via Settings → Sound.  We ask CoreAudio
# directly for the *current* default so the persistent stream lands on
# the same device AVAudioEngine would resolve to (i.e. what the
# operator actually hears today, not what was default an hour ago).
#
# ``JAEGER_AUDIO_OUTPUT`` env override:
#   - integer  → use that sounddevice index verbatim
#   - string   → fuzzy match against device names (case-insensitive
#                substring)

def _fourcc(s: str) -> int:
    return int.from_bytes(s.encode("ascii"), "big")


class _AudioObjectPropertyAddress(ctypes.Structure):
    _fields_ = [
        ("mSelector", c_uint32),
        ("mScope", c_uint32),
        ("mElement", c_uint32),
    ]


def _query_macos_default_output_name() -> Optional[str]:
    """Return the live macOS default output device name, or None if
    we're not on macOS / the CoreAudio call fails."""
    if sys.platform != "darwin":
        return None
    try:
        ca = ctypes.CDLL("/System/Library/Frameworks/CoreAudio.framework/CoreAudio")
        cf = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
    except OSError:
        return None

    ca.AudioObjectGetPropertyData.argtypes = [
        c_uint32, POINTER(_AudioObjectPropertyAddress),
        c_uint32, c_void_p,
        POINTER(c_uint32), c_void_p,
    ]
    ca.AudioObjectGetPropertyData.restype = c_int
    cf.CFStringGetCString.argtypes = [c_void_p, c_void_p, c_int, c_uint32]
    cf.CFStringGetCString.restype = c_int
    cf.CFRelease.argtypes = [c_void_p]

    # Step 1: ask the system object for the default output device ID.
    addr_dev = _AudioObjectPropertyAddress(
        _fourcc("dOut"), _fourcc("glob"), 0,
    )
    dev_id = c_uint32(0)
    size = c_uint32(4)
    err = ca.AudioObjectGetPropertyData(
        1,  # kAudioObjectSystemObject
        byref(addr_dev), 0, None,
        byref(size), byref(dev_id),
    )
    if err != 0 or dev_id.value == 0:
        return None

    # Step 2: ask that device for its CFString name.
    addr_name = _AudioObjectPropertyAddress(
        _fourcc("lnam"), _fourcc("glob"), 0,
    )
    cfstr = c_void_p(0)
    size = c_uint32(sizeof(c_void_p))
    err = ca.AudioObjectGetPropertyData(
        dev_id.value,
        byref(addr_name), 0, None,
        byref(size), byref(cfstr),
    )
    if err != 0 or not cfstr.value:
        return None

    buf = ctypes.create_string_buffer(256)
    ok = cf.CFStringGetCString(cfstr, buf, 256, 0x08000100)  # UTF-8
    name = buf.value.decode("utf-8", errors="replace") if ok else None
    cf.CFRelease(cfstr)
    return name


def resolve_output_device(sd: Any) -> Optional[int]:
    """Pick the sounddevice output device index that matches the live
    macOS default.  Returns None to let PortAudio pick its own default
    when CoreAudio can't tell us anything (non-macOS, query failed)."""
    # Env override wins.
    override = os.environ.get("JAEGER_AUDIO_OUTPUT")
    if override:
        try:
            return int(override)
        except ValueError:
            sub = override.lower().strip()
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] > 0 and sub in d["name"].lower():
                    return i

    target = _query_macos_default_output_name()
    if not target:
        return None
    nlc = target.lower()
    # Exact match first, then substring fallback.
    exact = None
    fuzzy = None
    for i, d in enumerate(sd.query_devices()):
        if d["max_output_channels"] <= 0:
            continue
        nm = d["name"].lower()
        if nm == nlc:
            exact = i
        elif nlc in nm or nm in nlc:
            if fuzzy is None:
                fuzzy = i
    return exact if exact is not None else fuzzy


# ── persistent player ────────────────────────────────────────────────
#
# Same shape as ``voice_assistant_persistent.py::PersistentPlayer``,
# with one addition: ``start()`` resolves the live macOS default device
# so PortAudio's stale "default" can't route TTS to a silent monitor.

class PersistentSoundDevicePlayer:
    """Long-lived sounddevice OutputStream + feed queue.

    Stream opens once and stays running for the whole process
    lifetime, closed at exit by :meth:`close`.  All TTS chunks go
    through :meth:`enqueue` (non-blocking); callers
    :meth:`mark_end` + :meth:`wait_until_drained` to wait until
    everything queued has actually played.

    Why a queue + callback instead of per-utterance ``sd.play``: it
    matches the production voice-app pattern (Discord, Zoom, FaceTime,
    Logic Pro).  Stream resources stay allocated for the session; the
    audio thread pulls samples on demand instead of us pushing them.
    Same shape as the AVAudioEngine version that will land alongside
    this in step 2 of the 0.3.0 refactor.
    """

    def __init__(self, samplerate: int = 24000, channels: int = 1) -> None:
        self.samplerate = int(samplerate)
        self.channels = int(channels)
        # Queue items: np.ndarray (audio) or None (end-of-message marker).
        self._q: "queue.Queue[Any]" = queue.Queue()
        # Buffer the callback is currently writing out of.
        self._current: np.ndarray = np.zeros(0, dtype=np.float32)
        self._drained = threading.Event()
        self._drained.set()           # idle = drained
        self._stream: Any = None
        # Resolved at start() so callers can log it.
        self.device_index: Optional[int] = None
        self.device_name: Optional[str] = None

    # ── lifecycle ─────────────────────────────────────────────────────

    def start(self) -> None:
        """Open the persistent OutputStream.  Idempotent."""
        if self._stream is not None:
            return
        import sounddevice as sd  # deferred import — keeps cold imports fast

        device = resolve_output_device(sd)
        try:
            info = sd.query_devices(device if device is not None
                                    else sd.default.device[1])
            self.device_index = device
            self.device_name = info["name"]
        except Exception:  # noqa: BLE001 — informational only
            self.device_name = "(unknown)"

        self._stream = sd.OutputStream(
            samplerate=self.samplerate,
            channels=self.channels,
            dtype="float32",
            blocksize=int(self.samplerate * 0.02),     # 20 ms
            callback=self._cb,
            device=device,
        )
        self._stream.start()

    def close(self) -> None:
        """Stop + close the stream.  Idempotent.  Safe to call at any
        point on the main thread; the audio callback won't fire after
        ``stop()`` returns."""
        if self._stream is None:
            return
        try:
            self._stream.stop()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._stream.close()
        except Exception:  # noqa: BLE001
            pass
        self._stream = None
        # Clear residual queue state.
        self._current = np.zeros(0, dtype=np.float32)
        with self._q.mutex:
            self._q.queue.clear()
        self._drained.set()

    def is_open(self) -> bool:
        return self._stream is not None

    # ── callback ──────────────────────────────────────────────────────

    def _cb(self, outdata, frames: int, _t, _s) -> None:
        """Audio thread: pull samples from the queue, write to
        ``outdata``.  Fills remainder with silence on underrun so the
        stream stays alive and ready for the next ``enqueue``."""
        i = 0
        while i < frames:
            if len(self._current) == 0:
                try:
                    item = self._q.get_nowait()
                except queue.Empty:
                    outdata[i:, 0] = 0.0
                    return
                if item is None:
                    # End-of-message marker — unblock waiter, silence rest.
                    self._drained.set()
                    outdata[i:, 0] = 0.0
                    return
                self._current = item
            take = min(frames - i, len(self._current))
            outdata[i:i + take, 0] = self._current[:take]
            self._current = self._current[take:]
            i += take

    # ── producer side ────────────────────────────────────────────────

    def enqueue(self, audio: np.ndarray) -> None:
        """Append a chunk to the play queue.  Non-blocking — caller
        keeps going (Kokoro keeps synthesizing chunk N+1 while chunk N
        is playing).  ``audio`` must be float32 mono at
        ``self.samplerate``; empty / None chunks are silently dropped."""
        if audio is None:
            return
        if not isinstance(audio, np.ndarray):
            audio = np.asarray(audio, dtype=np.float32)
        elif audio.dtype != np.float32:
            audio = audio.astype(np.float32)
        if audio.size == 0:
            return
        self._drained.clear()
        self._q.put(audio)

    def mark_end(self) -> None:
        """Put an end-of-message sentinel on the queue.  The callback
        fires :attr:`_drained` when it pulls this marker — i.e. once
        every chunk enqueued *before* the marker has played."""
        self._q.put(None)

    def wait_until_drained(self, timeout: float = 60.0) -> bool:
        """Block until the audio thread has consumed an end marker.
        Returns ``False`` on timeout."""
        return self._drained.wait(timeout=timeout)
