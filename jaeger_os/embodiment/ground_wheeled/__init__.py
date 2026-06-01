"""Ground-wheeled embodiment — differential-drive base + lidar.

Stub for future work. Mobile but ground-bound; manipulation skills
that need arms don't load on this body class (no ``arms`` /
``gripper`` capability). Navigation + perception skills do.
"""

from __future__ import annotations


CAPABILITIES: set[str] = {
    "diff_drive",
    "lidar",
    "camera",
    "imu",
}

KIND = "ground_wheeled"
