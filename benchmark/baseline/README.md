# Baseline benchmarks — pre-refactor capture

This directory is the **frozen snapshot** of Jaeger's behaviour and
performance under the current `pydantic-ai`-based agent loop. The
JaegerAgent refactor (Phase 1+) is compared against these numbers.

## Why

Without a captured baseline, any subjective claim of "the new framework
is faster" or "tool routing got better" is unfalsifiable. With one, we
can point at concrete rows and say what changed.

## Capture (do this BEFORE Phase 1 starts)

```bash
cd /Users/jonathanjenkins/GITHUB/JROS
./benchmark/baseline/capture.sh
```

That script runs all four levels through the existing
`boot_for_tui` + `run_command` entry point, scores them, and freezes:

- `benchmark/baseline/level{1,2,3,4}_rows.jsonl` — per-prompt
  observations (prompt, tool sequence, answer, latency, error)
- `benchmark/baseline/level{1,2,3,4}.log` — stdout / scoring summary
- `benchmark/baseline/manifest.json` — git SHA, model name, ctx, host
  CPU + RAM, capture timestamp — so the numbers are pinned to a
  reproducible state

## Compare (after Phase 1+)

Run the same script in a JaegerAgent-built tree. The level scripts
write into `benchmark/levels/level{N}_rows.jsonl` (not the baseline
dir), so the two snapshots sit side-by-side.

```bash
./benchmark/baseline/compare.sh
```

Diffs the two row sets prompt-by-prompt, highlights:

- Routing changes (different tool picked for the same prompt)
- Tool-arg drift
- Latency deltas (median + p95)
- Final-answer character delta
- Any new errors

## What "better" looks like

| Metric | Baseline target | Refactor target |
|---|---|---|
| L1 routing accuracy | matches current (~97%) | ≥ baseline |
| L2 multi-step success | matches current (~83%) | ≥ baseline |
| L3 multi-turn success | matches current (~67%) | **≥ 75%** — the resume + history-compaction work pays off here |
| L4 recovery success | matches current | ≥ baseline |
| Median turn latency (fast tier) | capture | ≤ baseline |
| `time_to_first_tool_call` | capture | ≤ baseline |
| Iterations per resolved turn | capture | ≤ baseline (less loop friction) |

Any regression on L1/L2/L4 is a refactor bug to fix.  An L3 improvement
is the most important success signal — that's the band where the new
loop's hook flexibility should pay off.

## What's NOT in the baseline

The baseline tests use the **default Jaeger instance + the default
local model**. They do not exercise:

- Cloud providers (separate benchmark set is worthwhile but out of
  Phase-0 scope)
- The voice loop
- MCP tools

The refactor's correctness on cloud paths is covered by per-adapter
unit tests in Phase 2/3. The voice loop and MCP keep their own integration
tests; neither's behaviour should be touched by the refactor.
