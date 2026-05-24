"""Quick L1-only A/B re-run after the Jinja arg-dict fix.

L1 alone takes ~25 min (vs 2h for full A/B). L1 routes single-turn so
the context overflow that hit L2/L3 doesn't apply — the signal here is
clean for the bug fix.
"""

from __future__ import annotations

import json
import os
import pathlib
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
for cand in (REPO, REPO / "src"):
    if str(cand) not in sys.path:
        sys.path.insert(0, str(cand))


def _reset_state() -> None:
    from jaeger_os.main import (
        _agent_cache, _jaeger_agents_by_session, _session_histories,
    )
    _agent_cache.clear()
    _jaeger_agents_by_session.clear()
    _session_histories.clear()
    from benchmark.levels._runner import _run_turn_via_new_agent
    if hasattr(_run_turn_via_new_agent, "_agents"):
        _run_turn_via_new_agent._agents.clear()  # type: ignore[attr-defined]


def _run_side(client: object, side: str, out_dir: pathlib.Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    from importlib import import_module
    module = import_module("benchmark.levels.level1_routing")
    started = time.perf_counter()
    rows = module.run_level(client)
    elapsed = time.perf_counter() - started
    rows_path = out_dir / "level_1_rows.jsonl"
    with rows_path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")
    print(f"[{side} L1] {len(rows)} cases in {elapsed:.1f}s → {rows_path.name}",
          flush=True)


def main() -> int:
    from benchmark.levels._runner import boot_jaeger_client

    print("=== boot ===", flush=True)
    boot = boot_jaeger_client(warmup=True)
    print("=== booted ===", flush=True)

    try:
        os.environ.pop("JAEGER_USE_NEW_AGENT", None)
        _reset_state()
        _run_side(boot.client, "legacy_l1_postfix", REPO / "benchmark" / "legacy_l1_postfix")

        os.environ["JAEGER_USE_NEW_AGENT"] = "1"
        _reset_state()
        _run_side(boot.client, "jaeger_agent_l1_postfix",
                  REPO / "benchmark" / "jaeger_agent_l1_postfix")
    finally:
        try:
            boot.cleanup()
        except Exception:  # noqa: BLE001
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
