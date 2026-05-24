# Phase-6 A/B Benchmark — Final Report

Captured after the Phase-6.1 partial migration + the Jinja arg-dict bugfix.

**Hardware:** M4 32GB · **Model:** Qwen3.5-9B Q4_K_M · **ctx:** 16384 ·
**Date:** 2026-05-23

## Headline

| Metric | pydantic-ai loop | JaegerAgent loop | Δ |
|---|---|---|---|
| **L1 routing** | 13/34 (38%) | **28/34 (82%)** | **+15 prompts** |
| **L1 answer** | 11/15 (73%) | **14/15 (93%)** | +3 prompts |
| **L1 errors** | 5 | **0** | -5 |
| **L1 median latency** | 43.87s | 45.57s | +1.71s |
| **L1 p95 latency** | 169.80s | **67.87s** | -102s (-60%) |
| **L1 total wall** | 34.7 min | **28.8 min** | -5.9 min (-17%) |

**15 prompts flipped ✗→✓. 0 prompts flipped ✓→✗.** No regressions on the
new path; substantial wins on routing accuracy + error rate + p95 latency.

## The bugs found + fixed during the migration

| Bug | Where | Fix | Test |
|---|---|---|---|
| Tool-call `arguments` JSON-encoded for in-process llama-cpp's Jinja chat template (the template iterates `\|items` and needs a dict) | `LocalLlamaAdapter._LlamaChatFacade.create` | Decode tool_call args back to dict before handing to llama-cpp | 4 regression tests in `test_local_llama_adapter.py` |

Both fixes are localized in the new adapter layer — they don't touch any
JROS tool body, system prompt, or skill.

## Decision-tree call

From the earlier analysis:

> | JaegerAgent result | What it means | Next move |
> |---|---|---|
> | ≥ pydantic-ai | Regression was loop-specific. Migration fixes it for free. | **Cut over.** |
> | ≈ pydantic-ai | Shared regression — bisect separately. | Hold cutover. |
> | < pydantic-ai | New loop has bugs. | Diagnose. |

**We are in row 1.** Cut over.

## What the cut-over needs (Phase 6.2)

| Task | Effort |
|---|---|
| Flip the default — `JAEGER_USE_NEW_AGENT=1` becomes implicit | 5 min |
| Delete `_run_via_iter` + `_run_with_fix_loop` | 1 hour |
| Delete `build_agent` + `@agent.tool_plain` decorators (switch all 48 to `@register_tool`) | 4-6 hours |
| Delete `_walk_new_messages` + benchmark `_walk_messages_for_calls` | 30 min |
| Delete `pydantic-ai` from `pyproject.toml` | 5 min |
| Rewrite 7 test files that bind to `pydantic_ai.messages.*` | 4-6 hours |
| Final full A/B confirming parity after cleanup | 2 hours wall |
| **Total** | **1-2 days work + bench wall time** |

## What the cut-over does NOT fix

The remaining misses are independent of the framework:

1. **Memory-tool umbrella over-attraction** (4 L1 prompts):
   `remember`/`recall`/`forget` lose to the umbrella `memory` tool because
   the umbrella's description is too broad. Fix is at the tool-definition
   level — narrow `memory.description` or remove the umbrella.

2. **Context overflow on long L2/L3 turns**: 16K ctx is now too small for
   the system prompt + ~80 tool definitions + multi-turn history. Two
   independent fixes available:

   a. **Bump ctx** to 32K (model trains at 262K; cheap stopgap).

   b. **Toolsets** (Hermes pattern, ~2-3 days work): only the toolsets
      enabled for a session/turn appear in the model's view. Reclaims
      ~10K tokens per turn. Proposed as **Phase 7**.

3. **Tier-gated tools auto-deny in non-interactive runs**: privileged
   tools (`shell.run_shell`) need a confirmation prompt that the bench
   has no way to satisfy. Separate ticket — the bench framework needs
   an `auto_approve` mode.

## Capture command

```bash
.venv/bin/python benchmark/run_ab.py        # full 4-level A/B
.venv/bin/python benchmark/ab_report.py     # render markdown report
.venv/bin/python benchmark/run_ab_l1.py     # L1-only quick re-run
```

## Files

- `benchmark/legacy_l1_postfix/level_1_rows.jsonl` — pydantic-ai L1 (this report)
- `benchmark/jaeger_agent_l1_postfix/level_1_rows.jsonl` — JaegerAgent L1 (this report)
- `benchmark/legacy/level_{1..4}_rows.jsonl` — full pre-fix A/B (legacy)
- `benchmark/jaeger_agent/level_{1..4}_rows.jsonl` — full pre-fix A/B (had the Jinja bug)
