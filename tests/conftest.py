"""Pytest configuration for the Jaeger-OS framework test suite.

Kept deliberately small — the framework tests are self-contained and do
not need fixtures. ``QT_QPA_PLATFORM`` is defaulted to ``offscreen`` so
any interface test that imports a GUI toolkit does not hard-abort on a
headless runner before pytest can report a normal result.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
