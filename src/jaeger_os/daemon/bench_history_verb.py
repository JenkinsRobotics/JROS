"""``jaeger bench history`` — rolling leaderboard across every bench run.

Each bench run today writes a fresh artifact (``benchmark/flat/<ts>/``
for single-model runs, ``benchmark/sweep/RESULTS_<ts>.md`` and
``sweep_rows.jsonl`` for multi-model sweeps). Nothing aggregates them —
"what's the best model on this machine?" requires walking the
directory tree and reading each file.

This verb fixes that. It scans the bench history, attributes results
to models, and renders a leaderboard sorted by best routing accuracy.
Two output modes:

  jaeger bench history            # print the leaderboard
  jaeger bench history --write    # also write benchmark/HISTORY.md

Data sources (skipped silently when missing):

  * ``benchmark/sweep/sweep_rows.jsonl`` — one row per per-model sweep
    invocation. Older format from before the metrics block existed.
  * ``benchmark/flat/<ts>/summary.json`` — modern per-run summaries.
    Now stamped with ``model_name`` / ``model_path`` (added 2026-05-27).
    Older summaries land in the "unknown model" bucket — call those
    out with a count so the user can re-run them if it matters.

We do not parse the rendered ``RESULTS_*.md`` files — the JSONL +
JSON sources have everything the markdown does and more.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
from collections import defaultdict
from datetime import datetime
from typing import Any, Iterable


# Benchmark-generation cutoff. The 2026-05-27 pipeline overhaul
# (drift-parser fixes, skip-final removal, the 51-case corpus
# replacing the old 34-case Level-1 suite, real tokenizer TPS)
# made earlier runs non-comparable — a May-24 "67%" and a May-27
# "67%" measure different things. The leaderboard defaults to
# showing ONLY runs on/after this date so the ranking is
# apples-to-apples. ``--all`` (or ``--since`` with an earlier date)
# brings the historical runs back for archaeology.
_DEFAULT_SINCE = "2026-05-27"

# Minimum case count for a run to count toward the leaderboard.
# Debugging mini-benches (``--limit 3/5/10``) trivially hit 100%
# routing and pollute the "best route%" column. The full corpus is
# 51 cases; a threshold of 50 keeps full runs, drops the noise, and
# tolerates a one-off corpus tweak. ``--min-cases 0`` disables the
# filter for partial-run analysis.
_DEFAULT_MIN_CASES = 50


def _cmd_bench_history_argv(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="jaeger bench history", add_help=False,
    )
    parser.add_argument(
        "--write", action="store_true",
        help="also write benchmark/HISTORY.md",
    )
    parser.add_argument(
        "--family", default=None,
        help="filter by model family substring (e.g. 'gemma' or 'qwen')",
    )
    parser.add_argument(
        "--top", type=int, default=0,
        help="cap output to top N entries by best routing % (0 = all)",
    )
    parser.add_argument(
        "--since", default=_DEFAULT_SINCE,
        help=f"only include runs on/after this date (YYYY-MM-DD). "
             f"Default {_DEFAULT_SINCE} — the current benchmark "
             f"generation. Older runs used a different corpus/pipeline "
             f"and aren't comparable.",
    )
    parser.add_argument(
        "--all", action="store_true",
        help="include every run regardless of date (overrides --since). "
             "Use for archaeology across benchmark generations.",
    )
    parser.add_argument(
        "--min-cases", type=int, default=_DEFAULT_MIN_CASES,
        help=f"only count runs with at least this many cases (default "
             f"{_DEFAULT_MIN_CASES}). Excludes debugging mini-benches "
             f"(--limit 3/5) that trivially hit 100%%. Set 0 to disable.",
    )
    parser.add_argument(
        "--include-unknown", action="store_true",
        help="include runs with no model attribution (the 'unknown' "
             "bucket from before model_name was stamped). Excluded by "
             "default — an unnamed run can't be compared to anything.",
    )
    parser.add_argument("-h", "--help", action="store_true")
    args = parser.parse_args(argv)
    if args.help:
        print(
            "usage: jaeger bench history [--write] [--family STR] "
            "[--top N] [--since YYYY-MM-DD] [--all]\n"
            "\n"
            "Rolling leaderboard across bench runs on this machine.\n"
            "Reads sweep + flat-bench artifacts and aggregates per model.\n"
            "\n"
            "  --write       also write benchmark/HISTORY.md\n"
            "  --family STR  only show models whose name contains STR\n"
            "  --top N       cap to top-N by routing %\n"
            f"  --since DATE  only runs on/after DATE (default {_DEFAULT_SINCE},\n"
            "                the current benchmark generation)\n"
            "  --all         include every run regardless of date\n",
            file=sys.stderr,
        )
        return 0

    repo = _repo_root()
    since = None if args.all else args.since
    md = render_history_md(
        repo,
        since=since,
        min_cases=args.min_cases,
        include_unknown=args.include_unknown,
        family=args.family,
        top=args.top,
    )
    print(md)

    if args.write:
        out_path = repo / "benchmark" / "HISTORY.md"
        out_path.write_text(md, encoding="utf-8")
        print(f"\nwrote {out_path}", file=sys.stderr)
    return 0


def render_history_md(
    repo: pathlib.Path,
    *,
    since: str | None = _DEFAULT_SINCE,
    min_cases: int = _DEFAULT_MIN_CASES,
    include_unknown: bool = False,
    family: str | None = None,
    top: int = 0,
) -> str:
    """Collect → filter → aggregate → render the leaderboard markdown.
    Pure: no printing, no file writes. The CLI verb and the
    auto-update hook both call this so the filtering logic lives in
    one place."""
    entries = list(_collect_entries(repo))
    if since:
        entries = [e for e in entries if _ts_to_date(e["ts"]) >= since]
    if min_cases and min_cases > 0:
        entries = [e for e in entries if e.get("cases", 0) >= min_cases]
    if not include_unknown:
        entries = [e for e in entries if e.get("model") != "unknown"]
    if family:
        needle = family.lower()
        entries = [e for e in entries if needle in e["model"].lower()]
    aggregated = _aggregate_by_model(entries)
    if top and top > 0:
        aggregated = aggregated[:top]
    return _render(aggregated, all_entries=entries,
                   total_entries=len(entries), since=since)


def write_history_md(repo: pathlib.Path | None = None) -> pathlib.Path | None:
    """Silently (re)generate ``benchmark/HISTORY.md`` with the default
    current-generation filters. Returns the path written, or ``None``
    if the repo / benchmark dir can't be located. Best-effort — never
    raises, so a bench run can call it as a fire-and-forget finalizer
    without risking the run's exit status.

    This is the auto-update hook: ``run_model_sweep.py`` calls it once
    at the end of a sweep, and ``run_flat_bench.py`` calls it after a
    standalone run, so the leaderboard is always current without a
    manual ``jaeger bench history --write``."""
    try:
        repo = repo or _repo_root()
        out_path = repo / "benchmark" / "HISTORY.md"
        if not out_path.parent.exists():
            return None
        md = render_history_md(repo)
        out_path.write_text(md, encoding="utf-8")
        return out_path
    except Exception:  # noqa: BLE001 — auto-update must never break a bench
        return None


# ── collection ─────────────────────────────────────────────────


def _collect_entries(repo: pathlib.Path) -> Iterable[dict[str, Any]]:
    """Walk both bench artifact directories. Each yielded entry has:

      {model, family, source, ts, pass_rate, route_pct, p50_s,
       p95_s, avg_latency_s, tokens_per_sec, tokens_source, cases,
       run_dir}

    Missing fields default to 0 / None / empty so the renderer's
    defensive ``.get()`` calls don't have to special-case anything.
    """
    yield from _from_sweep_jsonl(repo)
    yield from _from_flat_summaries(repo)


def _from_sweep_jsonl(repo: pathlib.Path) -> Iterable[dict[str, Any]]:
    """Older format. ``benchmark/sweep/sweep_rows.jsonl`` is one
    JSON-per-line of ``ModelResult`` dataclasses, written by
    ``run_model_sweep.py`` after each model finishes."""
    path = repo / "benchmark" / "sweep" / "sweep_rows.jsonl"
    if not path.exists():
        return
    try:
        with path.open(encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                cases = int(row.get("cases", 0) or 0)
                if cases <= 0:
                    # Row recorded an error or zero-progress timeout —
                    # skip from the leaderboard but you can still see
                    # it via ``cat sweep_rows.jsonl``.
                    continue
                route_pct = (
                    100 * row.get("route_ok", 0) / cases if cases else 0.0
                )
                yield {
                    "model": row.get("name") or "unknown",
                    "family": _family_of(row.get("name") or ""),
                    "source": "sweep",
                    "ts": row.get("ts") or "",
                    "pass_rate": route_pct / 100.0,
                    "route_pct": route_pct,
                    "p50_s": float(row.get("p50_turn_s", 0.0) or 0.0),
                    "p95_s": 0.0,    # not captured in older format
                    "avg_latency_s": (
                        float(row.get("elapsed_s", 0.0) or 0.0) / cases
                        if cases else 0.0
                    ),
                    "tokens_per_sec": 0.0,
                    "tokens_source": "n/a",
                    "cases": cases,
                    "run_dir": "benchmark/sweep/",
                }
    except OSError:
        return


def _from_flat_summaries(repo: pathlib.Path) -> Iterable[dict[str, Any]]:
    """Walk ``benchmark/flat/`` for per-run summaries.

    Two layouts supported because we restructured the tree
    2026-05-27 to nest by model:

      * NEW: ``benchmark/flat/<model>/<ts>/summary.json``
      * OLD: ``benchmark/flat/<ts>/summary.json`` (timestamp-only,
        pre-restructure — these always land in the "unknown" bucket
        since model attribution was added at the same time as
        nesting).

    The walk is depth-1 inspect: any dir directly under ``flat/``
    with a ``summary.json`` is a legacy timestamped run; any dir
    without one is a model-named bucket whose grandchildren are
    timestamped runs.
    """
    flat_root = repo / "benchmark" / "flat"
    if not flat_root.exists():
        return
    summary_paths: list[pathlib.Path] = []
    for child in sorted(flat_root.iterdir()):
        if not child.is_dir():
            continue
        # OLD layout (pre-2026-05-27): ``flat/<ts>/summary.json``.
        own_summary = _find_summary_in(child)
        if own_summary is not None:
            summary_paths.append(own_summary)
            continue
        # NEW layout: ``flat/<model>/<ts>/`` — peek one level deeper.
        for run_dir in sorted(child.iterdir()):
            if not run_dir.is_dir():
                continue
            nested = _find_summary_in(run_dir)
            if nested is not None:
                summary_paths.append(nested)
    for summary_path in summary_paths:
        try:
            summary = json.loads(summary_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        run_dir = summary_path.parent
        metrics = summary.get("metrics") or {}
        model = summary.get("model_name") or "unknown"
        route_total = int(summary.get("routing_total", 0) or 0)
        route_passed = int(summary.get("routing_passed", 0) or 0)
        route_pct = (100 * route_passed / route_total) if route_total else 0.0
        yield {
            "model": model,
            "family": _family_of(model),
            "source": "flat",
            "ts": summary.get("run_id") or run_dir.name,
            "pass_rate": float(summary.get("pass_rate", 0.0) or 0.0),
            "route_pct": route_pct,
            "p50_s": float(metrics.get("p50_latency_s", 0.0) or 0.0),
            "p95_s": float(metrics.get("p95_latency_s", 0.0) or 0.0),
            "avg_latency_s": float(metrics.get("avg_latency_s", 0.0) or 0.0),
            "tokens_per_sec": float(
                metrics.get("answer_tokens_per_sec", 0.0) or 0.0
            ),
            "tokens_source": metrics.get(
                "answer_tokens_source", "whitespace_estimate",
            ),
            "cases": int(summary.get("total", 0) or 0),
            # Make the run_dir path relative to the repo so it works
            # regardless of layout (legacy ``flat/<ts>/`` vs new
            # ``flat/<model>/<ts>/``).
            "run_dir": str(run_dir.relative_to(repo)) + "/",
        }


def _find_summary_in(run_dir: pathlib.Path) -> pathlib.Path | None:
    """Locate the summary file in a run directory.

    Two filename conventions coexist:

      * OLD (pre-2026-05-27 evening): ``summary.json``
      * NEW: ``<model>-<ts>-summary.json`` — same model+ts as the
        parent path, repeated in the filename so an out-of-context
        copy still self-identifies.

    We try the old name first (cheaper — single ``Path.exists()``
    call), then glob for the new shape. Returns None if neither
    exists (incomplete run, malformed dir, etc.)."""
    old = run_dir / "summary.json"
    if old.exists():
        return old
    new_candidates = sorted(run_dir.glob("*-summary.json"))
    if new_candidates:
        # Multiple matches → take the lexicographically last (newest
        # timestamp by suffix) — shouldn't happen in practice but
        # defensive.
        return new_candidates[-1]
    return None


def _family_of(name: str) -> str:
    """Best-effort family attribution from the model filename."""
    low = name.lower()
    if "gemma" in low:
        return "gemma"
    if "qwen" in low:
        return "qwen"
    if "llama" in low:
        return "llama"
    if "mistral" in low or "ministral" in low:
        return "mistral"
    if "phi" in low:
        return "phi"
    return "other"


# ── aggregation ────────────────────────────────────────────────


def _aggregate_by_model(entries: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group entries by model name; for each model report best route%,
    latest p50, last run timestamp, run count. Sorted by best
    route% descending, then by latest p50 ascending (so two equal
    accuracy models rank the faster one first).

    A model with 5 runs at ``77.2 / 67.6 / 90.1 / 88.0 / 80.0`` reports
    best=90.1; the ``latest_*`` columns track whichever run had the
    most recent timestamp."""
    by_model: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for e in entries:
        by_model[e["model"]].append(e)

    out: list[dict[str, Any]] = []
    for model, runs in by_model.items():
        # Sort runs newest-first so ``runs[0]`` is the latest.
        runs.sort(key=lambda r: r["ts"], reverse=True)
        latest = runs[0]
        best_route = max(r["route_pct"] for r in runs)
        best_pass = max(r["pass_rate"] for r in runs)
        out.append({
            "model": model,
            "family": latest["family"],
            "best_route_pct": best_route,
            "best_pass_rate": best_pass,
            "latest_p50_s": latest["p50_s"],
            "latest_p95_s": latest["p95_s"],
            "latest_tokens_per_sec": latest["tokens_per_sec"],
            "latest_tokens_source": latest["tokens_source"],
            "latest_route_pct": latest["route_pct"],
            "latest_ts": latest["ts"],
            "latest_cases": latest["cases"],
            "run_count": len(runs),
        })
    # Sort: best route% desc, then latest p50 asc.
    out.sort(key=lambda r: (-r["best_route_pct"], r["latest_p50_s"]))
    return out


# ── rendering ──────────────────────────────────────────────────


def _compact_ts(ts: str) -> str:
    """Normalise to YYYY-MM-DD HH:MM. Handles both ISO
    (``2026-05-24T17:27:00``) and bench-stamp
    (``20260527-122229``) shapes."""
    if not ts:
        return "—"
    if "T" in ts and len(ts) >= 16:
        return ts[:10] + " " + ts[11:16]
    if len(ts) == 15 and ts[8] == "-":
        return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]} {ts[9:11]}:{ts[11:13]}"
    return ts


def _ts_to_date(ts: str) -> str:
    """Extract a sortable ``YYYY-MM-DD`` from either timestamp shape.
    ISO ``2026-05-24T17:27:00`` → ``2026-05-24``; bench-stamp
    ``20260527-122229`` → ``2026-05-27``. Returns ``""`` for an
    unrecognised shape so it sorts BEFORE any real date (i.e. an
    undated run is treated as ancient and filtered out by --since)."""
    if not ts:
        return ""
    if "T" in ts and len(ts) >= 10:
        return ts[:10]
    if len(ts) >= 8 and ts[:8].isdigit():
        return f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
    return ""


def _render(
    rows: list[dict[str, Any]],
    *,
    all_entries: list[dict[str, Any]],
    total_entries: int,
    since: str | None = None,
) -> str:
    """Three-section report: per-model summary, all-time top runs,
    and the full chronological run log. Together they answer
    "how does each model compare today?" (summary), "what's the
    best we've ever recorded?" (top), and "what was today vs.
    yesterday vs. last week?" (chronological)."""
    if not rows:
        return (
            "# Jaeger-OS bench history\n\n"
            "No bench artifacts found. Run ``jaeger bench run`` or\n"
            "``jaeger bench compare`` first.\n"
        )
    now_iso = datetime.now().isoformat(timespec="seconds")
    window = (
        f"runs on/after **{since}** (current benchmark generation)"
        if since else "ALL runs (every benchmark generation)"
    )
    lines = [
        "# Jaeger-OS bench history",
        "",
        f"_Generated {now_iso} from {total_entries} run(s) across "
        f"`benchmark/sweep/` and `benchmark/flat/` — showing {window}._",
        "",
        "## Per-model leaderboard",
        "",
        "Best routing accuracy each model has ever scored on this "
        "machine. ``Latest *`` columns reflect the most recent run.",
        "",
        "| # | Model | Family | Best route% | Best pass% | Latest p50 s | "
        "Latest p95 s | Latest tok/s | Latest run | Runs |",
        "|---|---|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for i, r in enumerate(rows, start=1):
        latest_ts = _compact_ts(r["latest_ts"])
        lines.append(
            f"| {i} | `{r['model']}` | {r['family']} | "
            f"{r['best_route_pct']:.1f}% | "
            f"{100 * r['best_pass_rate']:.1f}% | "
            f"{r['latest_p50_s']:.2f} | "
            f"{r['latest_p95_s']:.2f} | "
            f"{r['latest_tokens_per_sec']:.1f} | "
            f"{latest_ts} | {r['run_count']} |"
        )

    # ── all-time top runs (top 10 by route%) ──────────────────
    top_runs = sorted(
        [e for e in all_entries if e["cases"] > 0],
        key=lambda e: (-e["route_pct"], e["p50_s"]),
    )[:10]
    if top_runs:
        lines += [
            "",
            "## Top 10 all-time best runs",
            "",
            "Sorted by routing % (then p50 asc). A single great run "
            "doesn't make a model great, but tracking peaks tells "
            "you what's achievable on this hardware.",
            "",
            "| # | Date | Model | Route% | p50 s | p95 s | TPS | Cases | Source |",
            "|---|---|---|---:|---:|---:|---:|---:|---|",
        ]
        for i, e in enumerate(top_runs, start=1):
            lines.append(
                f"| {i} | {_compact_ts(e['ts'])} | `{e['model']}` | "
                f"{e['route_pct']:.1f}% | {e['p50_s']:.2f} | "
                f"{e['p95_s']:.2f} | {e['tokens_per_sec']:.1f} | "
                f"{e['cases']} | {e['source']} |"
            )

    # ── full chronological log ───────────────────────────────
    chronological = sorted(
        all_entries, key=lambda e: e["ts"], reverse=True,
    )
    if chronological:
        # Track per-model peak so we can flag whether each row is at
        # or below the model's best — the "are we at peak?" signal.
        peak_by_model: dict[str, float] = {}
        for e in sorted(chronological, key=lambda x: x["ts"]):
            peak_by_model[e["model"]] = max(
                peak_by_model.get(e["model"], 0.0), e["route_pct"],
            )
        lines += [
            "",
            "## Full chronological log",
            "",
            f"Every run we have data for ({len(chronological)} total), "
            "newest first. ``vs peak`` shows the route% delta from "
            "this model's all-time best (0.0% = this run IS the peak).",
            "",
            "| Date | Model | Route% | p50 s | TPS | Cases | vs peak | Source |",
            "|---|---|---:|---:|---:|---:|---:|---|",
        ]
        for e in chronological:
            peak = peak_by_model.get(e["model"], e["route_pct"])
            delta = e["route_pct"] - peak
            if delta == 0.0:
                vs_peak = "**peak**"
            else:
                vs_peak = f"{delta:+.1f}pp"
            lines.append(
                f"| {_compact_ts(e['ts'])} | `{e['model']}` | "
                f"{e['route_pct']:.1f}% | {e['p50_s']:.2f} | "
                f"{e['tokens_per_sec']:.1f} | {e['cases']} | "
                f"{vs_peak} | {e['source']} |"
            )
    # Footer: token-source caveat.
    estimate_count = sum(
        1 for r in rows
        if r["latest_tokens_source"] == "whitespace_estimate"
    )
    if estimate_count:
        lines.append("")
        lines.append(
            f"_{estimate_count} model(s) report **whitespace-estimate** "
            f"tokens/sec — the adapter didn't surface a ``usage`` "
            f"field for those runs. Real tokenizer counts land when "
            f"the run was driven through llama-cpp / OpenAI / "
            f"Anthropic adapters with usage reporting._"
        )
    unknown = next((r for r in rows if r["model"] == "unknown"), None)
    if unknown:
        lines.append("")
        lines.append(
            f"_The ``unknown`` row aggregates "
            f"{unknown['run_count']} run(s) from before "
            f"``model_name`` was stamped into ``summary.json`` "
            f"(2026-05-27). Re-run those to attribute them._"
        )
    return "\n".join(lines) + "\n"


# ── path helper ───────────────────────────────────────────────


def _repo_root() -> pathlib.Path:
    """Walk up from this file to find the repo root (the dir that
    contains ``benchmark/``). Works for editable + installed wheels."""
    here = pathlib.Path(__file__).resolve()
    for parent in [here, *here.parents]:
        if (parent / "benchmark").is_dir():
            return parent
    # Fallback for unusual layouts.
    return here.parents[3]


__all__ = [
    "_cmd_bench_history_argv",
    "render_history_md",
    "write_history_md",
]
