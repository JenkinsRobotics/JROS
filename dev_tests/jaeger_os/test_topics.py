"""Test suite for ``jaeger_os.topics`` — the 0.4 node-topic SSOT.

Track A step 1 of the 0.4 roadmap.  These tests pin the topic-
namespace contract so future Bus + Node code can rely on it.
"""

from __future__ import annotations

import time

import pytest
from pydantic import ValidationError

from jaeger_os import topics


# ── registry shape ────────────────────────────────────────────────

def test_all_topics_matches_registry():
    """ALL_TOPICS must enumerate every key in TOPIC_TO_CLASS, no
    more no less.  Catches "added the constant but forgot to
    register" and "added to registry but forgot to expose"."""
    assert set(topics.ALL_TOPICS) == set(topics.TOPIC_TO_CLASS.keys())


def test_all_topics_are_unique():
    """No two topic constants resolve to the same string."""
    assert len(set(topics.ALL_TOPICS)) == len(topics.ALL_TOPICS)


def test_topic_namespace_shape():
    """Every topic begins with ``/sense/`` or ``/act/``.  The
    ``/health/*`` namespace is reserved for Track D; it shouldn't
    appear here yet."""
    for name in topics.ALL_TOPICS:
        assert name.startswith("/sense/") or name.startswith("/act/"), (
            f"topic {name!r} doesn't follow /sense/* | /act/* convention"
        )
        assert not name.startswith("/health/"), (
            f"{name!r} uses the /health/* namespace reserved for Track D"
        )


def test_class_for_topic_returns_topicmessage_subclass():
    """Every registered class derives from TopicMessage."""
    for name in topics.ALL_TOPICS:
        cls = topics.class_for_topic(name)
        assert issubclass(cls, topics.TopicMessage), (
            f"{cls.__name__} (registered for {name}) "
            f"isn't a TopicMessage subclass"
        )


def test_class_for_topic_raises_on_unknown():
    """Unknown topic strings are a hard error, not a silent miss."""
    with pytest.raises(KeyError):
        topics.class_for_topic("/sense/nonexistent")
    with pytest.raises(KeyError):
        topics.class_for_topic("not_even_namespaced")


# ── envelope ──────────────────────────────────────────────────────

def test_envelope_timestamp_is_recent():
    """t_emit_ns defaults to a recent nanosecond timestamp.  Tight
    bound so a slow CI doesn't false-pass."""
    before = time.time_ns()
    msg = topics.SpokenAck(ok=True)
    after = time.time_ns()
    assert before <= msg.t_emit_ns <= after, (
        f"t_emit_ns={msg.t_emit_ns} not in [{before}, {after}]"
    )


def test_envelope_correlation_id_defaults_to_none():
    """Non-RPC messages don't need a correlation_id."""
    msg = topics.AudioInFrame(samples=b"")
    assert msg.correlation_id is None


def test_envelope_correlation_id_round_trips_via_json():
    """An explicit correlation_id survives serialization."""
    msg = topics.SpeechCommand(text="hello", correlation_id="abc123")
    payload = msg.model_dump_json()
    parsed = topics.SpeechCommand.model_validate_json(payload)
    assert parsed.correlation_id == "abc123"


def test_envelope_topic_v_defaults_to_one():
    """First-version schema; bumps later only on breaking changes."""
    msg = topics.MotionCommand()
    assert msg.topic_v == 1


# ── per-class invariants ───────────────────────────────────────────

# Each (cls, required_kwargs) tuple covers one registered topic.
# The required kwargs are the minimum needed to instantiate the
# class without ValidationError; the test below uses them to prove
# the topic field pins to the right constant.
_INSTANTIABLE: tuple[tuple[type[topics.TopicMessage], dict], ...] = (
    (topics.AudioInFrame, {"samples": b""}),
    (topics.Transcript, {"text": ""}),
    (topics.VisionObservation, {"image_w": 0, "image_h": 0}),
    (topics.TouchReading, {"sensor_id": "", "in_contact": False}),
    (topics.ProprioReading, {}),
    (topics.SpokenAck, {"ok": True}),
    (topics.SpeechCommand, {"text": ""}),
    (topics.AudioOutFrame, {"samples": b""}),
    (topics.MotionCommand, {}),
    (topics.LightCommand, {}),
)


@pytest.mark.parametrize("cls,kwargs", _INSTANTIABLE)
def test_topic_class_pins_its_constant(cls, kwargs):
    """Default-construction of each class must produce ``msg.topic``
    equal to the registered constant.  Catches Literal-vs-constant
    typos at the class definition level."""
    msg = cls(**kwargs)
    name = msg.topic
    assert name in topics.TOPIC_TO_CLASS, (
        f"{cls.__name__}.topic = {name!r}, not a registered topic"
    )
    assert topics.TOPIC_TO_CLASS[name] is cls, (
        f"{name!r} resolves to {topics.TOPIC_TO_CLASS[name].__name__}, "
        f"not the expected {cls.__name__}"
    )


@pytest.mark.parametrize("cls,kwargs", _INSTANTIABLE)
def test_extra_fields_are_rejected(cls, kwargs):
    """``ConfigDict(extra='forbid')`` must catch unrecognised
    payload keys — otherwise a typo silently drops the value."""
    bad = {**kwargs, "this_field_does_not_exist": 42}
    with pytest.raises(ValidationError):
        cls(**bad)


# ── per-class field defaults that matter ──────────────────────────

def test_audio_in_frame_carries_binary_samples():
    """Binary samples survive ``model_dump()`` (dict form preserves
    the bytes object).  JSON round-trip on raw bytes is intentionally
    NOT supported — per ROADMAP_0.4.md open question #2, binary
    topics (audio_in, audio_out, vision) ride MessagePack on the
    wire which handles bytes natively.  Text topics ride JSON."""
    raw = b"\x00\x01\x02\xff\xfe\xfd"
    msg = topics.AudioInFrame(samples=raw, sample_rate=16000)
    dumped = msg.model_dump()
    assert dumped["samples"] == raw
    assert dumped["sample_rate"] == 16000


def test_text_topic_json_round_trips():
    """Text topics MUST survive JSON round-trip — they ride JSON on
    the wire by design."""
    original = topics.Transcript(
        text="hello world",
        confidence=0.92,
        language="en",
        is_final=True,
        duration_s=1.3,
        node_id="stt",
        correlation_id="utt-42",
    )
    payload = original.model_dump_json()
    parsed = topics.Transcript.model_validate_json(payload)
    assert parsed.text == "hello world"
    assert parsed.confidence == 0.92
    assert parsed.is_final is True
    assert parsed.duration_s == 1.3
    assert parsed.node_id == "stt"
    assert parsed.correlation_id == "utt-42"


def test_transcript_sensible_defaults():
    msg = topics.Transcript(text="hello")
    assert msg.confidence == 0.0
    assert msg.language == "en"
    assert msg.is_final is True
    assert msg.duration_s == 0.0


def test_vision_observation_boxes_default_empty():
    msg = topics.VisionObservation(image_w=640, image_h=480)
    assert msg.boxes == []
    assert msg.scene == ""


def test_motion_command_velocity_mode_default():
    """Velocity mode (use_waypoint=False) is the default."""
    msg = topics.MotionCommand(linear_x_mps=0.5, duration_s=1.0)
    assert msg.use_waypoint is False
    assert msg.target_xy == []


def test_motion_command_waypoint_mode_distinguishable():
    """When the caller flips use_waypoint, target_xy carries the goal."""
    msg = topics.MotionCommand(
        use_waypoint=True, target_xy=[1.0, 2.0],
    )
    assert msg.use_waypoint is True
    assert msg.target_xy == [1.0, 2.0]


def test_light_command_off_is_three_zeros():
    msg = topics.LightCommand()
    assert msg.rgb == [0, 0, 0]
    assert msg.pattern == "solid"
    assert msg.duration_ms == 0


def test_spoken_ack_carries_failure_reason():
    """Failure replies must propagate a human-readable reason."""
    msg = topics.SpokenAck(ok=False, reason="audio device locked")
    assert msg.ok is False
    assert msg.reason == "audio device locked"


# ── invariant we want at the API level ────────────────────────────

def test_topic_constants_match_class_topic_defaults():
    """Each module-level constant must equal the topic-default of
    the class registered for it.  Belt-and-suspenders against drift
    when a constant or a class default is renamed in isolation."""
    pairs = (
        (topics.SENSE_AUDIO_IN, topics.AudioInFrame),
        (topics.SENSE_TRANSCRIPT, topics.Transcript),
        (topics.SENSE_VISION, topics.VisionObservation),
        (topics.SENSE_TOUCH, topics.TouchReading),
        (topics.SENSE_PROPRIO, topics.ProprioReading),
        (topics.SENSE_SPOKEN, topics.SpokenAck),
        (topics.ACT_SPEECH, topics.SpeechCommand),
        (topics.ACT_AUDIO_OUT, topics.AudioOutFrame),
        (topics.ACT_MOTION, topics.MotionCommand),
        (topics.ACT_LIGHT, topics.LightCommand),
    )
    for constant, cls in pairs:
        # Get the topic field's default by inspecting model fields
        topic_field = cls.model_fields["topic"]
        assert topic_field.default == constant, (
            f"{cls.__name__}.topic default = {topic_field.default!r}, "
            f"expected {constant!r}"
        )
