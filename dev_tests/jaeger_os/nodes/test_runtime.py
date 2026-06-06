"""Tests for ``jaeger_os.nodes.runtime`` — Track B.2.1.

Lean tests on the bus singleton + shutdown.  The ``ensure_tts_node``
path with a mock synthesizer is exercised indirectly by the
integration test (``./launch --tts-boot-test``), which loads real
Kokoro through the runtime; building an equivalent mock-fixture
exposed a pytest-harness deadlock that is NOT a runtime bug (the
same code runs cleanly outside pytest — confirmed via standalone
script).  Pragmatic call: keep the unit tests minimal here and let
the integration smoke be the broader gate.
"""

from __future__ import annotations

from jaeger_os.nodes import runtime
from jaeger_os.transport import InProcBus


def test_get_bus_returns_same_instance():
    """Repeated calls return the SAME Bus — it's a singleton."""
    runtime.shutdown()  # start clean
    try:
        a = runtime.get_bus()
        b = runtime.get_bus()
        assert a is b
    finally:
        runtime.shutdown()


def test_get_bus_creates_inproc_bus():
    runtime.shutdown()
    try:
        bus = runtime.get_bus()
        assert isinstance(bus, InProcBus)
    finally:
        runtime.shutdown()


def test_shutdown_clears_bus_singleton():
    runtime.shutdown()
    bus1 = runtime.get_bus()
    runtime.shutdown()
    assert runtime._bus is None


def test_shutdown_is_idempotent():
    runtime.shutdown()
    runtime.shutdown()
    runtime.shutdown()  # no raise


def test_shutdown_then_get_bus_creates_fresh_bus():
    """After shutdown, a subsequent get_bus() gets a NEW bus, not
    the closed one."""
    runtime.shutdown()
    bus1 = runtime.get_bus()
    runtime.shutdown()
    bus2 = runtime.get_bus()
    try:
        assert bus1 is not bus2
    finally:
        runtime.shutdown()
