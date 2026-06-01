"""Embodiment layer — body classes the framework knows how to drive.

Layer between the instance (per-unit identity + state) and the
hardware. Each subpackage is a body class:

    desktop/          — keyboard, screen, speakers, mic, webcam
    humanoid/         — bipedal locomotion, dual-arm manipulation
    uav_quadcopter/   — MAVLink, GPS, flight envelope
    ground_wheeled/   — diff-drive, lidar

An instance picks ONE body class via ``embodiment.kind`` in its
``config.yaml``. Per-unit calibration (servo offsets, camera
intrinsics, IMU bias, learned waypoints) lives under
``<instance>/embodiment/calibration.yaml``.

This module is **phase-1 stub scaffolding**. The Embodiment Protocol
in :mod:`_interface` is a coarse sketch; concrete implementations
land as each body class becomes real work. See
:doc:`/docs/unified_architecture.md` §10 Embodiment model.
"""

from __future__ import annotations

from ._interface import (
    ActuatorCommand,
    ActuatorResult,
    Embodiment,
    Subscription,
)


__all__ = [
    "ActuatorCommand",
    "ActuatorResult",
    "Embodiment",
    "Subscription",
]
