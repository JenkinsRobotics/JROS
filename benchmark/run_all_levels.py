#!/usr/bin/env python3
"""Run every benchmark level against a single shared LLM boot.

  python benchmark/run_all_levels.py

Boots the model + jaeger pipeline ONCE, runs Levels 1-4 back-to-back,
writes per-level + unified markdown + jsonl. Saves wall time and
avoids loading Gemma four times.
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


LEVEL_MODULES = [
    (1, "benchmark.levels.level1_routing"),
    (2, "benchmark.levels.level2_multistep"),
    (3, "benchmark.levels.level3_multiturn"),
    (4, "benchmark.levels.level4_recovery"),
]

OUT_DIR = _REPO / "benchmark" / "levels"
UNIFIED_PATH = OUT_DIR / "BENCHMARK_all_levels.md"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-warmup", action="store_true",
                   help="Skip the llama-cpp prewarm pass")
    p.add_argument("--only", type=str, default="",
                   help="Comma-separated subset, e.g. --only 1,4")
    args = p.parse_args()

    selected: set[int] = set()
    if args.only.strip():
        try:
            selected = {int(x) for x in args.only.split(",") if x.strip()}
        except ValueError:
            print(f"--only must be comma-separated ints, got {args.only!r}",
                  file=sys.stderr)
            return 2

    print("=== Booting jaeger pipeline (shared across all levels) ===",
          flush=True)
    from benchmark.levels._runner import boot_jaeger_client
    boot_started = time.perf_counter()
    boot = boot_jaeger_client(warmup=not args.no_warmup)
    print(f"[boot] ready in {time.perf_counter() - boot_started:.1f}s\n",
          flush=True)

    summaries: list[dict[str, object]] = []
    grand_started = time.perf_counter()
    try:
        for level_num, mod_path in LEVEL_MODULES:
            if selected and level_num not in selected:
                continue
            print(f"\n=== Level {level_num} ({mod_path.split('.')[-1]}) ===",
                  flush=True)
            module = import_module(mod_path)
            l_started = time.perf_counter()
            rows = module.run_level(boot.client)
            l_elapsed = time.perf_counter() - l_started
            md = module.render_markdown(rows)
            md_path = OUT_DIR / f"BENCHMARK_level{level_num}.md"
            jsonl_path = OUT_DIR / f"level_{level_num}_rows.jsonl"
            md_path.write_text(md, encoding="utf-8")
            with jsonl_path.open("w", encoding="utf-8") as fh:
                for row in rows:
                    fh.write(json.dumps(row, default=str, ensure_ascii=False) + "\n")
            summaries.append({
                "level": level_num,
                "module": mod_path,
                "case_count": len(rows),
                "elapsed_s": l_elapsed,
                "md_path": str(md_path),
                "md": md,
            })
            print(f"[level {level_num}] {len(rows)} cases, {l_elapsed:.1f}s",
                  flush=True)
    finally:
        try:
            boot.cleanup()
        except Exception:
            pass

    grand_elapsed = time.perf_counter() - grand_started
    _write_unified(summaries, grand_elapsed)
    print(f"\nWrote {UNIFIED_PATH}", flush=True)
    return 0


def _write_unified(summaries: list[dict[str, object]],
                   grand_elapsed: float) -> None:
    lines = [
        "# Jaeger-OS — All-Levels Benchmark",
        "",
        f"Total wall time: **{grand_elapsed:.1f}s** across "
        f"{len(summaries)} level(s).",
        "",
        "## Per-level wall time",
        "",
        "| Level | Cases | Elapsed |",
        "|---|---:|---:|",
    ]
    for s in summaries:
        lines.append(
            f"| {s['level']} | {s['case_count']} | {s['elapsed_s']:.1f}s |"
        )
    lines.append("")
    for s in summaries:
        lines.append(s["md"])  # type: ignore[arg-type]
        lines.append("\n---\n")
    UNIFIED_PATH.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
