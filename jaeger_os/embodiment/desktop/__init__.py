"""Desktop embodiment — keyboard, screen, audio I/O, OS APIs.

Default body class for a developer machine / always-on assistant.
Mic + speaker for voice; screen + keyboard for visible UI surfaces;
no actuators that move matter.

Phase-1 stub — :data:`CAPABILITIES` declared so the skill loader
can filter physical skills correctly. Concrete adapter class
(satisfying :class:`jaeger_os.embodiment.Embodiment`) lands when the
embodiment layer wires through the boot path.
"""

from __future__ import annotations


CAPABILITIES: set[str] = {
    "keyboard",
    "screen",
    "speaker",
    "mic",
    "camera_webcam",
}

KIND = "desktop"
