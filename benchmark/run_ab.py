"""A/B benchmark — legacy pydantic-ai vs new JaegerAgent.

Boots the model once, runs all four levels with the legacy loop, then
flips ``JAEGER_USE_NEW_AGENT=1`` and runs all four levels again with
the new framework-free loop. Writes per-side row files into
``benchmark/legacy/`` and ``benchmark/jaeger_agent/``.

The model stays warm in-process so the boot cost is paid once, not
eight times — the latency comparison reflects loop overhead, not
cold-load variance.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time
from contextlib import redirect_stdout

REPO = pathlib.Path(__file__).resolve().parent.parent
for cand in (REPO, REPO / "src"):
    if str(cand) not in sys.path:
        sys.path.insert(0, str(cand))


LEVELS = [
    ("1", "benchmark.levels.level1_routing"),
    ("2", "benchmark.levels.level2_multistep"),
    ("3", "benchmark.levels.level3_multiturn"),
    ("4", "benchmark.levels.level4_recovery"),
]


def _reset_state() -> None:
    """Wipe per-session caches between A and B so each side starts from
    a clean conversation history. Mirrors what ``boot_for_tui`` does at
    process start, but selectively — the model + tools + system prompt
    stay loaded."""
    # Legacy session histories.
    from jaeger_os.main import (
        _agent_cache,
        _jaeger_agents_by_session,
        _session_histories,
    )
    _agent_cache.clear()
    _jaeger_agents_by_session.clear()
    _session_histories.clear()
    # New-agent bench-side cache.
    from benchmark.levels._runner import _run_turn_via_new_agent
    if hasattr(_run_turn_via_new_agent, "_agents"):
        _run_turn_via_new_agent._agents.clear()  # type: ignore[attr-defined]


def _run_side(client: object, side: str, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    from importlib import import_module
    for level_n, module_path in LEVELS:
        print(f"\n=== {side} · Level {level_n} ===", flush=True)
        module = import_module(module_path)
        started = time.perf_counter()
        rows = module.run_level(client)
        elapsed = time.perf_counter() - started
        rows_path = out_dir / f"level_{level_n}_rows.jsonl"
        with rows_path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")
        print(f"[{side} L{level_n}] {len(rows)} cases in {elapsed:.1f}s → {rows_path.name}",
              flush=True)


def main() -> int:
    from benchmark.levels._runner import boot_jaeger_client

    print("=== boot ===", flush=True)
    boot = boot_jaeger_client(warmup=True)
    print("=== booted ===", flush=True)

    try:
        # --- Side A: legacy ---
        os.environ.pop("JAEGER_USE_NEW_AGENT", None)
        _reset_state()
        _run_side(boot.client, "legacy", REPO / "benchmark" / "legacy")

        # --- Side B: new agent ---
        os.environ["JAEGER_USE_NEW_AGENT"] = "1"
        _reset_state()
        _run_side(boot.client, "jaeger_agent", REPO / "benchmark" / "jaeger_agent")

    finally:
        try:
            boot.cleanup()
        except Exception:  # noqa: BLE001
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
