"""topics.py — single source of truth for JROS 0.4 node topics.

Pure schemas + constants.  No transport dependency.  Both the
in-process Bus (Track A.2) and the future ZMQ transport (Track A.5)
import from here.

Every message is a Pydantic model that inherits from
:class:`TopicMessage` — the common envelope carries the topic name,
schema version, emit timestamp, sequence number, source node ID,
and an optional correlation ID for the tool/RPC pattern (the
operator's "tools = networking, nodes = execution" contract from
``dev_docs/ROADMAP_0.4.md``).

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
2. Add a Pydantic class that inherits from :class:`TopicMessage`,
   with ``topic: Literal[CONSTANT] = CONSTANT``.
3. Register it in :data:`TOPIC_TO_CLASS`.
4. Bump ``topic_v`` (default 1) only if you change a payload field
   in a breaking way; add a migration note in the docstring.

The test suite enforces that every constant in :data:`ALL_TOPICS`
has a registered class, that classes pin their constant, and that
``ConfigDict(extra="forbid")`` catches typos at validation time.
"""

from __future__ import annotations

import time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


# ── topic name constants ──────────────────────────────────────────

SENSE_AUDIO_IN = "/sense/audio_in"
SENSE_TRANSCRIPT = "/sense/transcript"
SENSE_VISION = "/sense/vision"
SENSE_TOUCH = "/sense/touch"
SENSE_PROPRIO = "/sense/proprio"
SENSE_SPOKEN = "/sense/spoken"

ACT_SPEECH = "/act/speech"
ACT_AUDIO_OUT = "/act/audio_out"
ACT_MOTION = "/act/motion"
ACT_LIGHT = "/act/light"


# ── common envelope ────────────────────────────────────────────────

class TopicMessage(BaseModel):
    """Common envelope every topic payload inherits.

    Subclasses define their own payload fields and pin ``topic`` to
    the matching constant via ``Literal``.
    """
    model_config = ConfigDict(extra="forbid")

    topic: str
    topic_v: int = 1
    t_emit_ns: int = Field(default_factory=lambda: time.time_ns())
    seq: int = 0
    node_id: str = ""
    correlation_id: str | None = None


# ── /sense/* ───────────────────────────────────────────────────────

class AudioInFrame(TopicMessage):
    """Raw mic samples from an audio_in node.  Binary payload —
    intended for MessagePack on the wire (JSON falls back to base64
    via Pydantic's default ``bytes`` encoder)."""
    topic: Literal["/sense/audio_in"] = SENSE_AUDIO_IN
    samples: bytes  # float32 little-endian PCM
    sample_rate: int = 16000
    channels: int = 1


class Transcript(TopicMessage):
    """STT output for a finalized utterance."""
    topic: Literal["/sense/transcript"] = SENSE_TRANSCRIPT
    text: str
    confidence: float = 0.0  # 0..1; 0.0 = unknown
    language: str = "en"
    is_final: bool = True
    duration_s: float = 0.0


class VisionObservation(TopicMessage):
    """Single frame of visual scene understanding.  YOLOv8-compatible
    box format so JP01-VCC01's existing CSI-camera inference drops in
    without translation."""
    topic: Literal["/sense/vision"] = SENSE_VISION
    image_w: int
    image_h: int
    boxes: list[dict] = Field(default_factory=list)
    # Each box: {cls: str, conf: float, xyxy: [x1, y1, x2, y2]}
    scene: str = ""  # optional scene-level description


class TouchReading(TopicMessage):
    """Contact-sensor reading from skin / bumpers."""
    topic: Literal["/sense/touch"] = SENSE_TOUCH
    sensor_id: str
    in_contact: bool
    force_n: float = 0.0


class ProprioReading(TopicMessage):
    """Encoder + IMU state from JP01-MC01 (ESP32 motion controller)."""
    topic: Literal["/sense/proprio"] = SENSE_PROPRIO
    joints_rad: list[float] = Field(default_factory=list)
    joints_vel_rps: list[float] = Field(default_factory=list)
    imu_quat: list[float] = Field(default_factory=list)   # [w, x, y, z]
    imu_omega: list[float] = Field(default_factory=list)  # [wx, wy, wz]


class SpokenAck(TopicMessage):
    """TTS-done acknowledgement.  Published by the tts node after the
    audio_out node finishes playing the synthesized clip.  The brain's
    text_to_speech tool waits on this (correlation_id-matched) before
    returning to the agent loop."""
    topic: Literal["/sense/spoken"] = SENSE_SPOKEN
    ok: bool
    duration_s: float = 0.0
    reason: str | None = None  # populated when ok=False


# ── /act/* ─────────────────────────────────────────────────────────

class SpeechCommand(TopicMessage):
    """Brain → tts: speak the given text.  Set ``correlation_id`` to
    match against the :class:`SpokenAck` reply for the tool-RPC
    pattern."""
    topic: Literal["/act/speech"] = ACT_SPEECH
    text: str
    voice: str = "af_heart"
    rate: float = 1.0  # 1.0 = normal speed


class AudioOutFrame(TopicMessage):
    """Synthesized audio frames bound for the speaker.  Binary
    payload; published by the tts node, consumed by audio_out."""
    topic: Literal["/act/audio_out"] = ACT_AUDIO_OUT
    samples: bytes  # float32 little-endian PCM
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
    target_xy: list[float] = Field(default_factory=list)


class LightCommand(TopicMessage):
    """Brain → led_ctrl (JP01-AVC01 Teensy): RGB LED state.

    ``rgb`` is a list of 3 ints in [0, 255].  ``pattern`` is the
    playback shape; "solid" holds the colour, "pulse"/"rainbow"
    animate, "off" blanks the strip.  ``duration_ms=0`` means hold
    until the next command."""
    topic: Literal["/act/light"] = ACT_LIGHT
    strip_id: str = "default"
    rgb: list[int] = Field(default_factory=lambda: [0, 0, 0])
    pattern: str = "solid"  # "solid" | "pulse" | "rainbow" | "off"
    duration_ms: int = 0


# ── registry + lookup ─────────────────────────────────────────────

TOPIC_TO_CLASS: dict[str, type[TopicMessage]] = {
    SENSE_AUDIO_IN: AudioInFrame,
    SENSE_TRANSCRIPT: Transcript,
    SENSE_VISION: VisionObservation,
    SENSE_TOUCH: TouchReading,
    SENSE_PROPRIO: ProprioReading,
    SENSE_SPOKEN: SpokenAck,
    ACT_SPEECH: SpeechCommand,
    ACT_AUDIO_OUT: AudioOutFrame,
    ACT_MOTION: MotionCommand,
    ACT_LIGHT: LightCommand,
}

ALL_TOPICS: tuple[str, ...] = tuple(TOPIC_TO_CLASS.keys())


def class_for_topic(topic: str) -> type[TopicMessage]:
    """Look up the Pydantic class for a topic string.

    Raises ``KeyError`` for unknown topics — call sites should treat
    this as a hard error (an unknown topic indicates schema drift,
    not a transient miss)."""
    return TOPIC_TO_CLASS[topic]


__all__ = [
    # Constants
    "SENSE_AUDIO_IN", "SENSE_TRANSCRIPT", "SENSE_VISION",
    "SENSE_TOUCH", "SENSE_PROPRIO", "SENSE_SPOKEN",
    "ACT_SPEECH", "ACT_AUDIO_OUT", "ACT_MOTION", "ACT_LIGHT",
    "ALL_TOPICS",
    # Envelope + concrete types
    "TopicMessage",
    "AudioInFrame", "Transcript", "VisionObservation",
    "TouchReading", "ProprioReading", "SpokenAck",
    "SpeechCommand", "AudioOutFrame", "MotionCommand", "LightCommand",
    # Registry
    "TOPIC_TO_CLASS", "class_for_topic",
]
