# Code review (2026-05-24) — what landed, what deferred

External review found 10 issues. This doc records the disposition and
the reasoning for each.

## Applied this round

| # | Finding | Fix |
|---|---|---|
| 1 | History trim could split assistant `tool_calls` from matching tool results | `ContextGuard._head_group_size` drops in groups — assistant + every following tool message whose `tool_call_id` matches one of its calls. 3 new tests in `test_context_guard.py`. |
| 2 | `AgentInterrupted` returned empty assistant message without setting `last_halt_reason` | Both interrupt sites now set `last_halt_reason="interrupted"`. Unified the string across the two sites (was "the turn was interrupted" in one, missing in the other). |
| 3 | `reset_read_tracker()` never called by Phase-9 `run_turn` | Called at the top of every `run_turn`, before the user message append, so a legitimate next-turn re-read isn't suppressed. |
| 6 | `normalize_tool_name` existed but no caller at the loop boundary; raw drifted names hit dispatch | `_dispatch_one_tool` now normalises once against `self._all_tools` before the `has_tool` check. The `tool_call` dict is patched in place so backstop bookkeeping sees the corrected name. |
| 7 | Skip-final could end multi-step turns prematurely | Added `_looks_multistep(user_message)` heuristic — patterns like "and then", "first … then", "step 1 … step 2" suppress the short-circuit. Conservative bias: false positives just take the full loop (one extra model call), false negatives silently drop user work. |
| 8 | Generic exception catch lost permission/safety types; Three Laws block existed but wasn't wrapping the system prompt | Tool dispatch now sets `error_type` + `retryable` + (when applicable) `required_tier` on the result dict; `PermissionDenied` / `ConfirmationRequired` / `HumanOverrideRequired` are tagged `retryable=false`. `build_system_prompt` wraps with `with_three_laws(...)` so the safety frame is the first block. |
| 10 | Latency log fields zeroed for the new path | Tool-progress callback in `main.py` accumulates per-turn tool time; the `LatencyReport` now carries `tool=tool_time` and `decision=loop_time` (total minus tool time) instead of both being 0. Adapter-level per-phase timings (TTFT, decision-vs-final split) still need adapter cooperation — separate follow-up. |
| 9 | Toolset default exposed everything | Already addressed by the **lean tool surface** work that landed earlier today — `agent.tools` is now a property that filters through `tool_visible()` per access. CORE + catalog by default; `JAEGER_FULL_TOOLS=1` is the bench escape hatch. See `docs/lean_surface.md`. |

Also fixed two bugs the user spotted in the TUI status bar (independent
of the review):

- **Loaded-ctx vs config-ctx**: `_current_ctx_max()` now prefers
  `client.loaded_ctx` over the wizard's `config.model.ctx`, so a model
  loaded at a different ctx is reflected immediately. New
  `_current_native_ctx_max()` surfaces the model's trained max
  (`n_ctx_train`), and `/runtime` flags it when the loaded ctx is more
  than 2× below native ("Qwen3-Coder-30B at 16K loaded but 262K trained
  — bump config.model.ctx").
- **0% gauge**: `_refresh_context_estimate` only walked the legacy
  pydantic-ai `msg.parts[].content` shape. The Phase-9 agent produces
  plain TypedDicts with `msg["content"]` directly — the estimator
  returned 0 for them, so the gauge stayed at 0%. Now handles both
  shapes. 4 new regression tests in `test_tui_rendering.py`.

## Deferred — with explicit reasoning

### #4 — Tool-guardrail controller wiring

Hooks (`on_before_tool_call` / `on_after_tool_call`) exist in
`AgentCallbacks` and are fired by `_dispatch_one_tool`, but `main.py`'s
`AgentCallbacks` construction only wires `tool_progress` and
`heartbeat`. A guardrail controller that detects repeated no-progress
calls / repeated failures / permission-denied retries would be a
medium-effort addition: it needs its own state, careful "does this
mirror or duplicate the loop-backstop" design, and tuning against the
benchmark suite to avoid regressing routing accuracy.

**Why deferred:** the loop-backstop already exists and catches the
worst case (identical-call hammering, semantic failure repeats). The
incremental value of a richer guardrail is real but small; building it
right is a focused work item, not a side change inside this review's
pass. Plan: lift Hermes's `tool_guardrails.ToolGuardrailController`
behind a feature flag, A/B against the benchmark, ship if it improves
L2/L4 numbers without regressing L1.

### #5 — Safe parallel tool execution

Read-only / path-disjoint tool batches could run in parallel; the
current dispatcher is sequential. Hermes does this carefully — they
exclude interactive, dangerous, computer-control, and robot tools, and
they preserve result order.

**Why deferred:** medium effort with subtle correctness ground.
Concurrent dispatch needs:

  - A clear policy for "what's safe to parallelise" (the `interactive`
    / `dangerous` flags on `ToolDef` are the obvious source — but
    `read_only` would need adding, and path-disjointness is per-call).
  - Result-order preservation so the model sees deterministic message
    ordering.
  - Interrupt semantics that don't strand a half-launched batch on
    cancel.
  - Bench data showing it moves L2/L4 meaningfully on local models.

Skipped this pass; tracked for a focused follow-up once the
already-landed wiring (group-aware trim, normalised names, tool-time
telemetry) gives us a clean baseline to measure against.
