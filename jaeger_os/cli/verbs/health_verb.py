"""``jaeger health`` — operator-side runtime health probe.

Sister verb to ``jaeger --doctor``. The split:

  ``--doctor``  → dependency + config-file checks. Runs BEFORE boot.
                  Pip packages, system libs, model.path exists, etc.
  ``health``    → runtime substrate checks. Runs AFTER boot. Verifies
                  the agent's actual moving parts: memory store works,
                  sandbox accepts writes, tool registry resolves, the
                  drift parser still parses canonical samples.

This is the operator's interface to the runtime probe — the agent
loop does NOT have a self-check tool of its own. Exposing one to the
model caused a routing pathology (prompts like "do a self check"
stalled in prefill on local Gemma checkpoints; the model dithered
over ``system_health`` vs ``system_status`` and llama.cpp's Metal
sampler hit a slow path under high first-token entropy). Matches
Hermes Agent's design: their ``hermes doctor`` is operator-only;
their agent loop has no self-test tool.

Surface:

  jaeger health              # 8 fast substrate checks (~1-3s)
  jaeger health --deep       # adds 3 live-agent turns (slow, real LLM)
  jaeger health --json       # machine-readable shape

Exits 0 when every probe passes, 1 otherwise — same convention as
``--doctor-check`` so scripts can chain on it.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path


def _cmd_health_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="jaeger health", add_help=False)
    parser.add_argument(
        "--deep", action="store_true",
        help="add three live-agent turns (free-text, read, sandbox "
             "write). Slow — each turn pays the model's per-turn cost.",
    )
    parser.add_argument(
        "--json", dest="as_json", action="store_true",
        help="emit the report as JSON instead of human-readable text",
    )
    parser.add_argument(
        "--instance", default=None,
        help="instance name (default: $JAEGER_INSTANCE_NAME or 'default')",
    )
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print(
            "usage: jaeger health [--deep] [--json] [--instance NAME]\n"
            "\n"
            "Runtime substrate probe. Verifies the agent's moving parts\n"
            "are healthy (memory store, sandbox, tool registry, skills,\n"
            "parser). Operator-side counterpart to ``--doctor`` which\n"
            "checks dependencies BEFORE boot.\n"
            "\n"
            "  --deep    add three live-agent turns (slow, real model call)\n"
            "  --json    JSON output for monitoring / scripting\n"
            "\n"
            "Exit code: 0 if every probe passes, 1 otherwise.",
            file=sys.stderr,
        )
        return 0

    # Bind the instance before probing — many checks read layout paths.
    layout = _bind_layout(args.instance)
    if layout is None:
        return 1

    from jaeger_os.core.diagnostics import run_health_checks
    report = run_health_checks(deep=bool(args.deep))

    if args.as_json:
        print(json.dumps(report, ensure_ascii=True, default=str))
    else:
        _print_human(report)

    return 0 if report.get("ok") else 1


def _bind_layout(instance_name: str | None):
    """Resolve + bind to an instance so the probe can read memory/
    skills paths. Returns None on error (with stderr message)."""
    try:
        from jaeger_os.core.instance.instance import (
            InstanceLayout, default_instance_name, resolve_instance_dir,
        )
        from jaeger_os.core.memory import memory as _memmod
        from jaeger_os.agent.tools import _common as _tcommon
    except Exception as exc:  # noqa: BLE001
        print(f"[jaeger health] could not load runtime: {exc}",
              file=sys.stderr)
        return None
    name = instance_name or default_instance_name()
    try:
        layout = InstanceLayout(root=resolve_instance_dir(name))
    except Exception as exc:  # noqa: BLE001
        print(f"[jaeger health] could not resolve instance {name!r}: {exc}",
              file=sys.stderr)
        return None
    if not layout.exists():
        print(f"[jaeger health] no instance {name!r} at {layout.root}",
              file=sys.stderr)
        return None
    try:
        _memmod.bind(layout)
        _tcommon._layout = layout
    except Exception as exc:  # noqa: BLE001
        print(f"[jaeger health] bind failed: {exc}", file=sys.stderr)
        return None
    return layout


def _print_human(report: dict) -> None:
    ok = bool(report.get("ok"))
    passed = report.get("passed", 0)
    total = report.get("total", 0)
    elapsed = report.get("elapsed_s", 0.0)
    deep = bool(report.get("deep", False))
    mode = "deep" if deep else "fast"
    head = "ok" if ok else "FAIL"
    print(f"jaeger health [{mode}]: {head} — {passed}/{total} passed "
          f"in {elapsed:.2f}s")
    for c in report.get("checks", []):
        mark = "✓" if c.get("ok") else "✗"
        name = c.get("name", "?")
        detail = c.get("detail", "")
        print(f"  {mark} {name:<18} {detail}")


__all__ = ["_cmd_health_argv"]
