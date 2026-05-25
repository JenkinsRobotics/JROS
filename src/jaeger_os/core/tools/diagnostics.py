"""Agent-callable runtime diagnostics.

  • system_health()  — run the lean health probe set against the
                       live agent and return ``{ok, passed, total,
                       checks: [...], elapsed_s}``.

This is the runtime counterpart to ``--doctor``:

  * ``--doctor`` validates DEPENDENCIES (pip pkgs, system libs,
    config.yaml parse, model.path exists) — runs **before** boot.
  * ``system_health`` validates the RUNTIME (memory round-trip,
    sandbox, tool registry, skills, parser) — runs **after** boot,
    on the same live process the user is talking to.

A failing dep check stops you booting; a failing health check means
something is broken AT runtime, on the surface that responds to the
user. Distinct failure modes deserve distinct probes.

Tier: READ_ONLY. The probe writes a tiny throwaway file under
``skills/`` and a throwaway memory key, both immediately cleaned up.
No external effects, safe to run anytime — including from a cron.
"""

from __future__ import annotations

from typing import Any


def system_health() -> dict[str, Any]:
    """Run the lean runtime health probe — 8 fast checks (<3s wall
    total, idempotent).

    Each check verifies a layer most likely to break silently after
    a config or refactor change: layout writable, sandbox accepts
    writes, memory round-trips, get_time / calculate respond, every
    CORE tool resolves, at least one skill is loaded, the drift
    parser handles a canonical emission.

    Returns ``{ok, passed, total, checks: [...], elapsed_s}``. ``ok``
    is True only when every probe passed — call this first when the
    user says "are you healthy?" / "self-check" / "diagnose yourself"
    and branch on the topline boolean.

    Use ``--doctor`` from the CLI for dep / config-file checks. Use
    ``run_benchmark`` for routing accuracy. Use this for "is the
    runtime actually working right now"."""
    from jaeger_os.core.diagnostics import run_health_checks
    return run_health_checks()


__all__ = ["system_health"]
