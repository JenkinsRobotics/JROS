#!/usr/bin/env bash
# Diff the current benchmark run against the frozen pre-refactor baseline.
# Run after Phase 1+ produces a new build of the level row files.
#
# Reads:
#   benchmark/baseline/level_N_rows.jsonl          (the baseline)
#   benchmark/levels/level_N_rows.jsonl            (the current run)
#
# Writes:
#   benchmark/baseline/diff_report.md              human-readable diff
set -euo pipefail

cd "$(dirname "$0")/../.."
PY="${PY:-./.venv/bin/python}"
if [[ ! -x "$PY" ]]; then PY="python3"; fi

$PY - <<'PYEOF'
"""Compare frozen pre-refactor benchmark rows against the current run.

Per-level: counts unchanged / regressed (tool sequence diverged) / improved
(new turn now succeeds where baseline failed). Latency: median + p95 deltas.
"""
import json
import statistics
from pathlib import Path

LEVELS = (1, 2, 3, 4)
BASELINE = Path("benchmark/baseline")
CURRENT = Path("benchmark/levels")

def load_rows(path: Path):
    if not path.is_file():
        return []
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]

report = ["# Benchmark diff — baseline vs current\n"]
manifest = BASELINE / "manifest.json"
if manifest.is_file():
    m = json.loads(manifest.read_text())
    report.append(f"**Baseline:** captured {m.get('captured_at')} · "
                  f"git `{m.get('git_sha')}` · framework `{m.get('framework')}` · "
                  f"model `{m.get('model')}`\n")
report.append("")

for level in LEVELS:
    base_rows = load_rows(BASELINE / f"level_{level}_rows.jsonl")
    cur_rows  = load_rows(CURRENT  / f"level_{level}_rows.jsonl")
    if not base_rows:
        report.append(f"## Level {level} — no baseline rows; skip\n")
        continue
    if not cur_rows:
        report.append(f"## Level {level} — no current rows; run the level first\n")
        continue

    by_prompt = {r["prompt"]: r for r in base_rows}
    unchanged = regressed = improved = 0
    latency_deltas: list[float] = []
    routing_diffs: list[str] = []

    for cur in cur_rows:
        base = by_prompt.get(cur["prompt"])
        if base is None:
            continue
        base_seq = tuple(base.get("tools_called") or [])
        cur_seq  = tuple(cur.get("tools_called")  or [])
        base_err = base.get("error")
        cur_err  = cur.get("error")
        if base_seq == cur_seq and bool(base_err) == bool(cur_err):
            unchanged += 1
        elif base_err and not cur_err:
            improved += 1
            routing_diffs.append(
                f"- ✓ recovered: {cur['prompt'][:60]!r} — was error, now {cur_seq}"
            )
        elif cur_err and not base_err:
            regressed += 1
            routing_diffs.append(
                f"- ✗ regressed: {cur['prompt'][:60]!r} — was {base_seq}, now error ({cur_err})"
            )
        elif base_seq != cur_seq:
            # Tool sequence changed but neither errored — flag for review
            regressed += 1
            routing_diffs.append(
                f"- Δ routing:  {cur['prompt'][:60]!r} — {base_seq} → {cur_seq}"
            )
        latency_deltas.append(
            float(cur.get("elapsed_s") or 0.0) - float(base.get("elapsed_s") or 0.0)
        )

    if latency_deltas:
        med = statistics.median(latency_deltas)
        p95 = statistics.quantiles(latency_deltas, n=20)[18] if len(latency_deltas) >= 20 else max(latency_deltas)
    else:
        med = p95 = 0.0
    arrow = lambda v: "+" if v >= 0 else ""
    report.append(f"## Level {level}\n")
    report.append(f"- unchanged: **{unchanged}** · improved: **{improved}** · "
                  f"regressed/changed: **{regressed}**")
    report.append(f"- median latency Δ: **{arrow(med)}{med:+.2f}s** · "
                  f"p95 latency Δ: **{arrow(p95)}{p95:+.2f}s**\n")
    if routing_diffs:
        report.append("### Per-prompt differences")
        report.extend(routing_diffs[:30])
        if len(routing_diffs) > 30:
            report.append(f"… {len(routing_diffs)-30} more")
        report.append("")

out = BASELINE / "diff_report.md"
out.write_text("\n".join(report))
print(out.read_text())
print(f"\n(also written to {out})")
PYEOF
