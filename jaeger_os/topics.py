"""topics.py — single source of truth for JROS 0.4 node topics.

Pure schemas + constants.  No transport dependency.  Both the
in-process Bus (Track A.2) and the future ZMQ transport (Track A.5)
import from here.

Schemas are :class:`msgspec.Struct`, not Pydantic models — 10×
faster on the transport hot path AND native MessagePack support
for the binary topics (audio frames, vision frames).  Pydantic
stays in JROS for config validation + tool schemas where its
richer ecosystem earns the overhead; transport schemas live where
microseconds matter.  See ``dev_docs/ROADMAP_0.4.md`` open question
#2 (resolved): JSON for text topics, MessagePack for binary topics.

Namespace
---------
* ``/sense/*`` — inputs the brain reads (mic, STT output, vision,
  touch, encoders, TTS-done acks).
* ``/act/*``   — commands the brain writes (speech requests, audio
  frames bound for speakers, motor commands, LED commands).
* ``/health/*`` — reserved for the per-node liveness ticks
  (Track D); not declared here yet.

Adding a new topic
------------------
1. Add an ``UPPER_SNAKE_CASE`` constant.
2. Add a :class:`msgspec.Struct` subclass that inherits
   :class:`TopicMessage`, with
   ``topic: Literal[CONSTANT] = CONSTANT``.
3. Register it in :data:`TOPIC_TO_CLASS`.
4. Only bump ``topic_v`` (default 1) on breaking payload changes;
   add a migration note in the docstring.

The test suite enforces that every constant in :data:`ALL_TOPICS`
has a registered class, that subclasses pin their constant, and
that ``forbid_unknown_fields=True`` catches typos at decode time.
"""

from __future__ import annotations

import time
from typing import Literal

import msgspec


# ── topic name constants ──────────────────────────────────────────

SENSE_AUDIO_IN = "/sense/audio_in"
SENSE_TRANSCRIPT = "/sense/transcript"
SENSE_USER_SPEECH_START = "/sense/user_speech_start"
SENSE_CAMERA_FRAME = "/sense/camera_frame"
# Back-compat alias for code that still imports the old 0.4 draft name.
# Do not register this as a separate topic; raw frames live on
# /sense/camera_frame. Reserve /sense/vision_analysis for inference output.
SENSE_VISION = SENSE_CAMERA_FRAME
SENSE_VISION_ANALYSIS = "/sense/vision_analysis"
SENSE_TOUCH = "/sense/touch"
SENSE_PROPRIO = "/sense/proprio"
SENSE_SPOKEN = "/sense/spoken"

ACT_SPEECH = "/act/speech"
ACT_AUDIO_OUT = "/act/audio_out"
ACT_MOTION = "/act/motion"
ACT_LIGHT = "/act/light"

# Control topics — interrupt / coordination commands ("stop /
# pause / resume what's in flight") rather than "do this action".
# Kept under ``/act/`` so the SUB-filter prefix at the brain side
# stays uniform; future control topics (mic_pause,
# stt_open_followup) will sit alongside.
ACT_SPEECH_STOP = "/act/speech_stop"


# ── common envelope ────────────────────────────────────────────────

class TopicMessage(
    msgspec.Struct,
    kw_only=True,
    forbid_unknown_fields=True,
):
    """Common envelope every topic payload inherits.

    ``kw_only=True`` lets subclasses freely mix required and default-
    bearing fields without dataclass-style ordering pain.

    ``forbid_unknown_fields=True`` makes msgspec raise on unknown
    keys during decode — analogous to Pydantic's ``extra="forbid"``
    so a typo'd field name on the wire is a hard error, not a
    silent drop.

    Subclasses pin ``topic`` to a Literal whose only value is the
    matching constant.  msgspec validates this at decode time too.
    """
    topic: str
    topic_v: int = 1
    t_emit_ns: int = msgspec.field(default_factory=time.time_ns)
    seq: int = 0
    node_id: str = ""
    correlation_id: str | None = None


# ── /sense/* ───────────────────────────────────────────────────────

class AudioInFrame(TopicMessage):
    """Raw mic samples from an audio_in node.  Binary payload —
    intended for MessagePack on the wire (msgspec encodes ``bytes``
    natively; JSON would need a base64 hop)."""
    topic: Literal["/sense/audio_in"] = SENSE_AUDIO_IN
    samples: bytes = b""  # float32 little-endian PCM
    sample_rate: int = 16000
    channels: int = 1


class Transcript(TopicMessage):
    """STT output for a finalized utterance."""
    topic: Literal["/sense/transcript"] = SENSE_TRANSCRIPT
    text: str = ""
    confidence: float = 0.0   # 0..1; 0.0 = unknown
    language: str = "en"
    is_final: bool = True
    duration_s: float = 0.0


class UserSpeechStart(TopicMessage):
    """Low-latency event emitted when the audio session detects
    sustained user speech.

    This is distinct from :class:`Transcript`: speech-start is for
    realtime interruption/barge-in and arrives before Whisper finalizes
    a phrase; transcript is the later semantic user utterance.
    """
    topic: Literal["/sense/user_speech_start"] = SENSE_USER_SPEECH_START


class CameraFrame(TopicMessage):
    """A single camera frame.  Binary payload — rides MessagePack
    on the wire so the encoded image bytes don't pay a base64 hop.

    Schema is intentionally lean: a camera node is a source, not
    an analyser.  No YOLO boxes, no scene descriptions, no
    detection metadata — those belong on a future
    ``/sense/vision_analysis`` topic published by a downstream
    inference node that consumes ``/sense/camera_frame``.

    Two source modes supported by the vision node (Track B.5):
        * USB camera (cv2.VideoCapture device index, local Mac)
        * TCP stream (frames pushed by a remote board over an
          Ethernet socket — today: JP01-VCC01 Jetson; tomorrow:
          any IP-streamable source)

    The brain doesn't care which mode produced a frame — same
    topic, same schema; only ``camera_id`` distinguishes sources
    when multiple cameras run at once.
    """
    topic: Literal["/sense/camera_frame"] = SENSE_CAMERA_FRAME
    image_w: int = 0
    image_h: int = 0
    encoding: str = "jpeg"  # "jpeg" | "png" | "raw_bgr8" | "raw_rgb8"
    frame_bytes: bytes = b""
    camera_id: str = "default"
    frame_seq: int = 0  # monotonic counter from the producing camera


class TouchReading(TopicMessage):
    """Contact-sensor reading from skin / bumpers."""
    topic: Literal["/sense/touch"] = SENSE_TOUCH
    sensor_id: str = ""
    in_contact: bool = False
    force_n: float = 0.0


class ProprioReading(TopicMessage):
    """Encoder + IMU state from JP01-MC01 (ESP32 motion controller)."""
    topic: Literal["/sense/proprio"] = SENSE_PROPRIO
    joints_rad: list[float] = msgspec.field(default_factory=list)
    joints_vel_rps: list[float] = msgspec.field(default_factory=list)
    imu_quat: list[float] = msgspec.field(default_factory=list)
    # imu_quat: [w, x, y, z]
    imu_omega: list[float] = msgspec.field(default_factory=list)
    # imu_omega: [wx, wy, wz]


class SpokenAck(TopicMessage):
    """TTS-done acknowledgement.  Published by the tts node after the
    audio_out node finishes playing the synthesized clip.  The brain's
    text_to_speech tool waits on this (correlation_id-matched) before
    returning to the agent loop."""
    topic: Literal["/sense/spoken"] = SENSE_SPOKEN
    ok: bool = False
    duration_s: float = 0.0
    reason: str | None = None  # populated when ok=False


# ── /act/* ─────────────────────────────────────────────────────────

class SpeechCommand(TopicMessage):
    """Brain → tts: speak the given text.  Set ``correlation_id`` to
    match against the :class:`SpokenAck` reply (the tool-RPC
    pattern)."""
    topic: Literal["/act/speech"] = ACT_SPEECH
    text: str = ""
    voice: str = "af_heart"
    rate: float = 1.0  # 1.0 = normal speed


class AudioOutFrame(TopicMessage):
    """Synthesized audio frames bound for the speaker.  Binary
    payload; published by the tts node, consumed by audio_out."""
    topic: Literal["/act/audio_out"] = ACT_AUDIO_OUT
    samples: bytes = b""  # float32 little-endian PCM
    sample_rate: int = 24000
    channels: int = 1


class MotionCommand(TopicMessage):
    """Brain → motor_ctrl (JP01-MC01 ESP32): motion command.

    Two complementary modes:
        * velocity — set ``linear_*``/``angular_z``, held for
          ``duration_s`` seconds.
        * waypoint — set ``use_waypoint=True`` and ``target_xy`` to
          [x, y] in metres (frame TBD by motor_ctrl).
    """
    topic: Literal["/act/motion"] = ACT_MOTION
    linear_x_mps: float = 0.0
    linear_y_mps: float = 0.0
    angular_z_rps: float = 0.0
    duration_s: float = 0.0
    use_waypoint: bool = False
    target_xy: list[float] = msgspec.field(default_factory=list)


class SpeechStop(TopicMessage):
    """Voice loop → TTS node: stop the current speech.  Barge-in
    primitive — when the STT side detects sustained user voice
    during TTS playback, the voice loop publishes this so the TTS
    node interrupts its synthesizer.  The TTS node then publishes
    a SpokenAck with ``ok=False`` / ``reason="interrupted"`` for
    any in-flight bus.request waiting on the matching
    correlation_id.

    Reasonably blast-radius'd: callers don't need to know which
    correlation_id is in flight; the TTS node maintains its own
    state.  Pass ``correlation_id`` if you want the ack to be tied
    back, otherwise the node uses whatever it's currently working
    on."""
    topic: Literal["/act/speech_stop"] = ACT_SPEECH_STOP
    reason: str = "interrupted"


class LightCommand(TopicMessage):
    """Brain → led_ctrl (JP01-AVC01 Teensy): RGB LED state.

    ``rgb`` is a list of 3 ints in [0, 255].  ``pattern`` is the
    playback shape; "solid" holds the colour, "pulse"/"rainbow"
    animate, "off" blanks the strip.  ``duration_ms=0`` means hold
    until the next command."""
    topic: Literal["/act/light"] = ACT_LIGHT
    strip_id: str = "default"
    rgb: list[int] = msgspec.field(default_factory=lambda: [0, 0, 0])
    pattern: str = "solid"  # "solid" | "pulse" | "rainbow" | "off"
    duration_ms: int = 0


# ── registry + lookup ─────────────────────────────────────────────

TOPIC_TO_CLASS: dict[str, type[TopicMessage]] = {
    SENSE_AUDIO_IN: AudioInFrame,
    SENSE_TRANSCRIPT: Transcript,
    SENSE_USER_SPEECH_START: UserSpeechStart,
    SENSE_CAMERA_FRAME: CameraFrame,
    SENSE_TOUCH: TouchReading,
    SENSE_PROPRIO: ProprioReading,
    SENSE_SPOKEN: SpokenAck,
    ACT_SPEECH: SpeechCommand,
    ACT_AUDIO_OUT: AudioOutFrame,
    ACT_MOTION: MotionCommand,
    ACT_LIGHT: LightCommand,
    ACT_SPEECH_STOP: SpeechStop,
}

ALL_TOPICS: tuple[str, ...] = tuple(TOPIC_TO_CLASS.keys())


def class_for_topic(topic: str) -> type[TopicMessage]:
    """Look up the msgspec.Struct subclass for a topic string.

    Raises ``KeyError`` for unknown topics — call sites should treat
    this as a hard error (an unknown topic indicates schema drift,
    not a transient miss)."""
    return TOPIC_TO_CLASS[topic]


__all__ = [
    # Constants
    "SENSE_AUDIO_IN", "SENSE_TRANSCRIPT", "SENSE_USER_SPEECH_START",
    "SENSE_CAMERA_FRAME", "SENSE_VISION", "SENSE_VISION_ANALYSIS",
    "SENSE_TOUCH", "SENSE_PROPRIO", "SENSE_SPOKEN",
    "ACT_SPEECH", "ACT_AUDIO_OUT", "ACT_MOTION", "ACT_LIGHT",
    "ACT_SPEECH_STOP",
    "ALL_TOPICS",
    # Envelope + concrete types
    "TopicMessage",
    "AudioInFrame", "Transcript", "UserSpeechStart", "CameraFrame",
    "TouchReading", "ProprioReading", "SpokenAck",
    "SpeechCommand", "AudioOutFrame", "MotionCommand", "LightCommand",
    "SpeechStop",
    # Registry
    "TOPIC_TO_CLASS", "class_for_topic",
]
