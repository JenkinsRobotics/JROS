#!/usr/bin/env python3
"""Run a single benchmark level.

  python benchmark/run_level.py 1   # routing
  python benchmark/run_level.py 2   # multi-step
  python benchmark/run_level.py 3   # multi-turn
  python benchmark/run_level.py 4   # recovery

Each run boots its own llama-cpp client + jaeger pipeline (so the
level can be exercised standalone) and writes:

  - benchmark/levels/BENCHMARK_levelN.md
  - benchmark/levels/level_N_rows.jsonl
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
from importlib import import_module


_REPO = pathlib.Path(__file__).resolve().parent.parent
for _candidate in (_REPO, _REPO / "src"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))
os.chdir(_REPO)


LEVEL_MODULES = {
    1: "benchmark.levels.level1_routing",
    2: "benchmark.levels.level2_multistep",
    3: "benchmark.levels.level3_multiturn",
    4: "benchmark.levels.level4_recovery",
}

OUT_DIR = _REPO / "benchmark" / "levels"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("level", type=int, choices=sorted(LEVEL_MODULES.keys()),
                   help="Which level to run (1-4)")
    p.add_argument("--no-warmup", action="store_true",
                   help="Skip the llama-cpp prewarm pass")
    args = p.parse_args()

    module = import_module(LEVEL_MODULES[args.level])

    print(f"\n=== Booting jaeger pipeline for Level {args.level} ===", flush=True)
    from benchmark.levels._runner import boot_jaeger_client
    started_boot = time.perf_counter()
    boot = boot_jaeger_client(warmup=not args.no_warmup)
    print(f"[boot] ready in {time.perf_counter() - started_boot:.1f}s.\n",
          flush=True)

    try:
        started_run = time.perf_counter()
        rows = module.run_level(boot.client)
        elapsed_run = time.perf_counter() - started_run
        print(f"\n[level {args.level}] {len(rows)} cases in {elapsed_run:.1f}s",
              flush=True)

        md = module.render_markdown(rows)
        md_path = OUT_DIR / f"BENCHMARK_level{args.level}.md"
        jsonl_path = OUT_DIR / f"level_{args.level}_rows.jsonl"
        md_path.write_text(md, encoding="utf-8")
        with jsonl_path.open("w", encoding="utf-8") as fh:
            for row in rows:
                fh.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")
        print(f"[level {args.level}] wrote {md_path}", flush=True)
        print(f"[level {args.level}] wrote {jsonl_path}", flush=True)
    finally:
        try:
            boot.cleanup()
        except Exception:
            pass

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
