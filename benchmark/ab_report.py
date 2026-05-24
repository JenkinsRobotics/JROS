"""Render an A/B comparison between two row-set directories.

Reads ``benchmark/legacy/level_{1..4}_rows.jsonl`` and
``benchmark/jaeger_agent/level_{1..4}_rows.jsonl`` and prints a per-level
scorecard + latency delta + per-prompt diff for the prompts that flipped.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
import sys
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent


def _load(path: pathlib.Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def _stats(rows: list[dict[str, Any]], key: str) -> tuple[int, int]:
    n = len(rows)
    ok = sum(1 for r in rows if r.get(key))
    return ok, n


def _latency(rows: list[dict[str, Any]]) -> tuple[float, float]:
    times = sorted(r.get("elapsed_s", 0.0) for r in rows)
    if not times:
        return 0.0, 0.0
    median = times[len(times) // 2]
    p95 = times[min(int(len(times) * 0.95), len(times) - 1)]
    return median, p95


def _pct(num: int, den: int) -> str:
    return f"{100*num/den:.0f}%" if den else "n/a"


# ── per-level scoring keys ─────────────────────────────────────────


LEVEL_PRIMARY = {
    1: "routing_ok",
    2: "tool_set_ok",
    3: "scenario_pass",
    4: "recovered",
}
LEVEL_SECONDARY = {
    1: "answer_ok",
    2: "answer_ok",
    3: None,  # L3 has only scenario_pass
    4: "no_hallucination",
}


def _level_label(level: int) -> str:
    return {1: "L1 routing", 2: "L2 multi-step",
            3: "L3 multi-turn", 4: "L4 recovery"}.get(level, f"L{level}")


def _key_for_match(level: int, row: dict[str, Any]) -> str:
    """Stable key for diffing the same prompt across runs."""
    if level == 3:
        # L3 rows are scenarios (s_idx), not single prompts.
        return f"s{row.get('s_idx', '?')}"
    return f"p{row.get('idx', '?')}"


def render(legacy_dir: pathlib.Path, new_dir: pathlib.Path) -> str:
    out: list[str] = []
    out.append("# Phase-6 A/B benchmark")
    out.append("")
    out.append(
        f"- **legacy** (`{legacy_dir.relative_to(REPO)}`): pydantic-ai loop"
    )
    out.append(
        f"- **jaeger_agent** (`{new_dir.relative_to(REPO)}`): "
        "framework-free `JaegerAgent` loop"
    )
    out.append("")
    out.append(
        "| Level | n | legacy | jaeger_agent | Δ | med (s) | p95 (s) |"
    )
    out.append("|---|---|---|---|---|---|---|")

    for level in (1, 2, 3, 4):
        a = _load(legacy_dir / f"level_{level}_rows.jsonl")
        b = _load(new_dir / f"level_{level}_rows.jsonl")
        if not a and not b:
            continue
        prim_key = LEVEL_PRIMARY[level]
        a_ok, a_n = _stats(a, prim_key)
        b_ok, b_n = _stats(b, prim_key)
        a_med, a_p95 = _latency(a)
        b_med, b_p95 = _latency(b)
        delta = (
            f"{b_ok - a_ok:+d}" if a_n == b_n else
            f"{_pct(b_ok, b_n)} vs {_pct(a_ok, a_n)}"
        )
        out.append(
            f"| {_level_label(level)} "
            f"| {a_n}/{b_n} "
            f"| {_pct(a_ok, a_n)} ({a_ok}/{a_n}) "
            f"| {_pct(b_ok, b_n)} ({b_ok}/{b_n}) "
            f"| {delta} "
            f"| {a_med:.2f} → {b_med:.2f} ({b_med - a_med:+.2f}) "
            f"| {a_p95:.2f} → {b_p95:.2f} ({b_p95 - a_p95:+.2f}) |"
        )

    out.append("")

    # Per-level diff: prompts where the primary score flipped.
    for level in (1, 2, 3, 4):
        a_rows = _load(legacy_dir / f"level_{level}_rows.jsonl")
        b_rows = _load(new_dir / f"level_{level}_rows.jsonl")
        if not a_rows or not b_rows:
            continue
        a_by_key = {_key_for_match(level, r): r for r in a_rows}
        b_by_key = {_key_for_match(level, r): r for r in b_rows}
        prim = LEVEL_PRIMARY[level]
        flips: list[str] = []
        for k in sorted(set(a_by_key) | set(b_by_key)):
            ar = a_by_key.get(k)
            br = b_by_key.get(k)
            if ar is None or br is None:
                continue
            a_ok = bool(ar.get(prim))
            b_ok = bool(br.get(prim))
            if a_ok == b_ok:
                continue
            arrow = "✓ → ✗" if a_ok and not b_ok else "✗ → ✓"
            prompt = (ar.get("prompt") or ar.get("name") or k)
            prompt_short = (
                prompt if len(str(prompt)) <= 60 else str(prompt)[:57] + "…"
            )
            flips.append(f"  - `{k}` **{arrow}** — {prompt_short}")
        if flips:
            out.append(f"## {_level_label(level)} — flipped prompts")
            out.append("")
            out.extend(flips)
            out.append("")

    # Latency deltas worth noting.
    out.append("## Per-level latency deltas (median, p95)")
    out.append("")
    out.append("| Level | legacy med | new med | Δ med | legacy p95 | new p95 | Δ p95 |")
    out.append("|---|---|---|---|---|---|---|")
    for level in (1, 2, 3, 4):
        a = _load(legacy_dir / f"level_{level}_rows.jsonl")
        b = _load(new_dir / f"level_{level}_rows.jsonl")
        if not a or not b:
            continue
        a_med, a_p95 = _latency(a)
        b_med, b_p95 = _latency(b)
        out.append(
            f"| {_level_label(level)} "
            f"| {a_med:.2f}s | {b_med:.2f}s | {b_med - a_med:+.2f}s "
            f"| {a_p95:.2f}s | {b_p95:.2f}s | {b_p95 - a_p95:+.2f}s |"
        )

    out.append("")
    return "\n".join(out)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--legacy", default=str(REPO / "benchmark" / "legacy"),
        help="Directory holding legacy level_N_rows.jsonl files",
    )
    p.add_argument(
        "--new", default=str(REPO / "benchmark" / "jaeger_agent"),
        help="Directory holding jaeger_agent level_N_rows.jsonl files",
    )
    p.add_argument(
        "-o", "--output", default=None,
        help="Write report to this path (default: stdout)",
    )
    args = p.parse_args()

    text = render(pathlib.Path(args.legacy), pathlib.Path(args.new))
    if args.output:
        pathlib.Path(args.output).write_text(text, encoding="utf-8")
        print(f"wrote {args.output}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
