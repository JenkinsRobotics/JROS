"""Lean runtime health probe.

The bug we're guarding against: a refactor or rename silently breaks
one of the layers the agent depends on at runtime (sandbox path
resolver, memory store schema, tool registration, drift parser) and
the failure only surfaces when a real user prompt happens to exercise
it. The probe runs every layer once on every invocation so the break
is loud and immediate.

This file pins:
  * each individual check returns a sane shape on success
  * a failing check is reported as ``ok=False`` with the reason
  * an exception inside a check is caught and reported (the probe
    keeps running through the rest of the list, not short-circuited)
  * the topline ``ok`` boolean is a strict AND across every probe
"""

from __future__ import annotations

import pytest

from jaeger_os.core.diagnostics import run_health_checks
from jaeger_os.core.diagnostics.probe import (
    DEFAULT_CHECKS,
    HealthCheck,
    HealthResult,
    _run_one,
)


# ── shape / runner contract ─────────────────────────────────────────


def test_runner_produces_one_result_per_check():
    checks = [
        HealthCheck("a", lambda: (True, "ok")),
        HealthCheck("b", lambda: (True, "ok")),
        HealthCheck("c", lambda: (True, "ok")),
    ]
    out = run_health_checks(checks)
    assert out["total"] == 3
    assert out["passed"] == 3
    assert out["ok"] is True
    assert [r["name"] for r in out["checks"]] == ["a", "b", "c"]


def test_failure_is_surfaced_without_short_circuit():
    """A failing check must not stop the rest of the probe — the
    operator wants the WHOLE picture, not just the first thing that
    broke."""
    calls: list[str] = []

    def make(name: str, ok: bool):
        def fn():
            calls.append(name)
            return ok, f"{name} detail"
        return HealthCheck(name, fn)

    out = run_health_checks([make("a", False), make("b", True), make("c", True)])
    assert calls == ["a", "b", "c"]
    assert out["ok"] is False
    assert out["passed"] == 2
    assert out["total"] == 3
    a, b, c = out["checks"]
    assert a["ok"] is False
    assert b["ok"] is True
    assert c["ok"] is True


def test_exception_inside_check_is_caught_as_failure():
    """A check that raises must not propagate — the probe is meant to
    diagnose, not crash. The exception text lands in ``detail``."""
    def boom():
        raise RuntimeError("synthetic")
    out = run_health_checks([HealthCheck("boom", boom)])
    assert out["ok"] is False
    assert out["passed"] == 0
    assert "synthetic" in out["checks"][0]["detail"]
    assert "RuntimeError" in out["checks"][0]["detail"]


def test_topline_ok_is_strict_and_across_every_check():
    """``ok`` flips False the moment ANY check fails, even with
    everything else passing."""
    out = run_health_checks([
        HealthCheck("a", lambda: (True, "")),
        HealthCheck("fail_one", lambda: (False, "")),
        HealthCheck("c", lambda: (True, "")),
    ])
    assert out["ok"] is False


def test_runner_records_elapsed_ms_per_check():
    """The elapsed_ms field exists and is non-negative — the operator
    uses it to spot a probe that suddenly takes 10x longer (the
    canary for a slow filesystem or a leaked file handle)."""
    out = run_health_checks([HealthCheck("instant", lambda: (True, ""))])
    assert out["checks"][0]["elapsed_ms"] >= 0
    assert isinstance(out["checks"][0]["elapsed_ms"], (int, float))


def test_run_one_wraps_callable_into_a_health_result():
    """``_run_one`` is the building block — single-check API.
    Returns a HealthResult with name, ok, detail, elapsed_ms."""
    r = _run_one(HealthCheck("solo", lambda: (True, "fine")))
    assert isinstance(r, HealthResult)
    assert r.name == "solo"
    assert r.ok is True
    assert r.detail == "fine"


# ── default probe set integrity ─────────────────────────────────────


def test_default_checks_include_every_advertised_probe():
    """The runtime probe set must include every layer the tool's
    docstring promises. A regression here would silently shrink the
    probe."""
    names = {c.name for c in DEFAULT_CHECKS}
    advertised = {
        "layout", "file_sandbox", "memory", "time", "calculate",
        "tool_registry", "skills_loaded", "drift_parser",
    }
    assert advertised.issubset(names), f"missing probes: {advertised - names}"


def test_default_checks_have_unique_names():
    """Duplicate names would collide in the result list and confuse
    any downstream renderer that keys off ``name``."""
    names = [c.name for c in DEFAULT_CHECKS]
    assert len(names) == len(set(names))
