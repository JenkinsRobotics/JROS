#!/usr/bin/env python3
"""Boot the jaeger pipeline, run the flat self-benchmark, print rows.

Subprocess entry point for ``run_model_sweep.py`` — each model gets a
clean Python interpreter so a crash on one doesn't poison the
others. Prints one ``[ROW <idx>]`` line per case with a stable shape
that the sweep driver greps for case totals + per-row latency.

The bench itself lives in :mod:`jaeger_os.core.bench`; that's the
same code path the live agent invokes via the ``run_benchmark`` tool.
This script is the offline counterpart — one boot, full corpus, no
agent layer in front.

Usage::

    python benchmark/run_flat_bench.py              # full corpus
    python benchmark/run_flat_bench.py --tags routing
    python benchmark/run_flat_bench.py --limit 5    # smoke
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time


_REPO = pathlib.Path(__file__).resolve().parent.parent
for _candidate in (_REPO, _REPO / "src"):
    if str(_candidate) not in sys.path:
        sys.path.insert(0, str(_candidate))
os.chdir(_REPO)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--no-warmup", action="store_true",
                   help="Skip the llama-cpp prewarm pass")
    p.add_argument("--tags", type=str, default="",
                   help="Comma-separated tag filter (routing, multistep, "
                        "multiturn, recovery, memory, files, web, code, "
                        "audio, schedule). Empty = full corpus.")
    p.add_argument("--ids", type=str, default="",
                   help="Comma-separated case ids — re-run specific cases.")
    p.add_argument("--limit", type=int, default=0,
                   help="Cap number of cases (after filtering). 0 = none.")
    args = p.parse_args()

    print("=== Booting jaeger pipeline ===", flush=True)
    boot_started = time.perf_counter()
    from jaeger_os.main import boot_for_tui
    boot = boot_for_tui(
        instance_name="default", with_memory=True, warmup=not args.no_warmup,
    )
    load_s = time.perf_counter() - boot_started
    print(f"[boot] loaded in {load_s:.2f}s", flush=True)

    from jaeger_os.core.bench import run_bench, summarise

    tag_list = [t.strip() for t in (args.tags or "").split(",") if t.strip()]
    id_list = [i.strip() for i in (args.ids or "").split(",") if i.strip()]
    cap = args.limit if args.limit and args.limit > 0 else None

    def _on_row(idx: int, total: int, case_id: str,
                passed: bool, elapsed_s: float) -> None:
        # Stable one-line-per-row format. ``run_model_sweep.py`` greps
        # this; tag-along output (errors, etc.) goes to stderr or stays
        # inside the result dict so it doesn't break parsing.
        mark = "✓" if passed else "✗"
        print(f"  [ROW {idx:02d}] {case_id:40s} pass={mark}  "
              f"{elapsed_s:5.2f}s", flush=True)

    started = time.perf_counter()
    try:
        rows = run_bench(boot.client, tags=tag_list or None,
                         ids=id_list or None, limit=cap, progress=_on_row)
    finally:
        try:
            boot.cleanup()
        except Exception:  # noqa: BLE001 — cleanup is best-effort
            pass
    wall = time.perf_counter() - started

    summary = summarise(rows)
    summary["wall_s"] = round(wall, 2)
    summary["load_s"] = round(load_s, 2)

    out_dir = _REPO / "benchmark" / "flat" / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "rows.jsonl").write_text(
        "\n".join(json.dumps(r, default=str, ensure_ascii=False)
                  for r in summary["rows"]) + "\n",
        encoding="utf-8",
    )
    (out_dir / "summary.json").write_text(
        json.dumps({k: v for k, v in summary.items() if k != "rows"},
                   indent=2, default=str, ensure_ascii=False),
        encoding="utf-8",
    )

    total = summary["total"] or 1
    print(f"\n{summary['passed']}/{summary['total']} passed "
          f"({100 * summary['passed'] / total:.0f}%); "
          f"errors={summary['errors']}; wall={wall:.1f}s", flush=True)
    print(f"Wrote {out_dir}", flush=True)
    return 0 if summary["passed"] == summary["total"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
