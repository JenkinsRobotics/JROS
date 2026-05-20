"""UAV (quadcopter) embodiment — flight controller via MAVLink.

Stub for future work. No arms / no gripper; the body's "actuation"
is the flight envelope itself (waypoints, attitude setpoints,
takeoff/land/RTL). Cognitive skills load; manipulation-class
physical skills do not.
"""

from __future__ import annotations


CAPABILITIES: set[str] = {
    "flight_controller",
    "gps",
    "altitude_hold",
    "camera",
    "imu",
}

KIND = "uav_quadcopter"
