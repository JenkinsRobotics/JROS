"""Humanoid embodiment — bipedal locomotion + dual-arm manipulation.

Stub for future work. Real adapter wires through JROS (see
``docs/lilith/JROS_INTEGRATION.md``) or directly to ROS2/manipulator
drivers, depending on the placement decision in
:doc:`/docs/unified_architecture.md` §10.6.

:data:`CAPABILITIES` is the union a typical humanoid (Atlas-class)
declares; specific units may declare a subset (e.g. wheeled base
instead of bipedal). Per-unit declarations override the class
default at load time.
"""

from __future__ import annotations


CAPABILITIES: set[str] = {
    "arms",
    "gripper",
    "bipedal",
    "camera",
    "mic",
    "speaker",
    "lidar",
    "imu",
}

KIND = "humanoid"
