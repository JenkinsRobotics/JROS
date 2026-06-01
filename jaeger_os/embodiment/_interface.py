"""Embodiment Protocol — the contract every body class implements.

Each subpackage under ``embodiment/`` exposes a class satisfying
this Protocol. The agent loop never imports a concrete body class
directly; it goes through the active instance's embodiment
(resolved at boot from ``config.yaml``'s ``embodiment.kind`` field).

Phase-1 sketch — see :doc:`/docs/unified_architecture.md` §10.5. The
surface here is intentionally coarse; the first concrete body class
to land (`desktop/`) will refine the signatures and add specifics
the sketch doesn't yet capture. Keep it minimal until a real use
case forces an addition.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Protocol, runtime_checkable


@dataclass
class ActuatorCommand:
    """One actuator action request. ``kind`` identifies the actuator
    (e.g. ``"left_arm_pose"``, ``"speaker_play"``); ``payload`` carries
    the body-class-specific parameters."""

    kind: str
    payload: dict[str, Any]


@dataclass
class ActuatorResult:
    """Return shape from :meth:`Embodiment.actuator_dispatch`."""

    ok: bool
    detail: dict[str, Any]
    error: str | None = None


@dataclass
class Subscription:
    """Handle returned from :meth:`Embodiment.sensor_subscribe`.

    The body class keeps the callback alive until ``unsubscribe()`` is
    called. Cancellation is best-effort — frames already in flight may
    still arrive.
    """

    topic: str
    unsubscribe: Callable[[], None]


@runtime_checkable
class Embodiment(Protocol):
    """A body class. One picked per instance.

    Implementations declare ``capabilities`` (a set of capability
    strings the body supports — e.g. ``{"arms", "gripper", "camera"}``)
    so the skill loader can gate physical skills to bodies that can
    actually run them. A skill manifest's ``embodiment_requires:``
    field is checked against this set at load time.
    """

    capabilities: set[str]
    kind: str

    def get_capability_info(self, name: str) -> dict[str, Any]:
        """Return capability-specific metadata (e.g. for ``"arms"``:
        ``{"count": 2, "dof": 7, "max_payload_kg": 2.5}``). Raises
        :class:`KeyError` if the capability isn't supported."""
        ...

    def actuator_dispatch(self, cmd: ActuatorCommand) -> ActuatorResult:
        """Execute an actuator action. Synchronous; callers wrap in
        threads if they need async."""
        ...

    def sensor_subscribe(
        self, topic: str, callback: Callable[[dict[str, Any]], None],
    ) -> Subscription:
        """Subscribe ``callback`` to frames on ``topic`` (e.g.
        ``"camera_rgb"``, ``"imu"``). Returns a :class:`Subscription`
        with an ``unsubscribe()`` method."""
        ...

    def shutdown(self) -> None:
        """Release any held resources (devices, threads, subprocesses)
        on instance shutdown."""
        ...
